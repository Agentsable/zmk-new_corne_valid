"""Read the keymap the board is actually running, over the ZMK Studio RPC.

The board is the only place the Studio-stored keymap exists: Studio writes it to
NVS and nothing in this repo sees it. Everything else the flasher renders comes
from committed source, so this is the one path to what is really on the keys.

Transport is the USB CDC port the studio-rpc-usb-uart snippet exposes on the
left half, framed with the SOF/ESC/EOF bytes from zmk/app/src/studio/msg_framing.h
and carrying protobuf from the pinned cormoran/zmk-studio-messages fork.

Two constraints are structural, not bugs:
  * keymap.get_keymap is ZMK_STUDIO_RPC_HANDLER_SECURED, so the board must be
    unlocked from the keyboard first. There is no host-side unlock.
  * The port is exclusive. zmk.studio in a browser holds it, and then we cannot.
"""
import time

import serial
from serial.serialutil import SerialException

from zmk_proto import (behaviors_pb2, core_pb2, keymap_pb2,  # noqa: F401  (registers types)
                       meta_pb2, studio_pb2)

SOF, ESC, EOF = 0xAB, 0xAC, 0xAD
UNLOCKED = "ZMK_STUDIO_CORE_LOCK_STATE_UNLOCKED"


class RpcError(Exception):
    """Carries a `kind` the UI can branch on rather than matching message text."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def _frame(payload: bytes) -> bytes:
    out = bytearray([SOF])
    for b in payload:
        if b in (SOF, ESC, EOF):
            out.append(ESC)
        out.append(b)
    out.append(EOF)
    return bytes(out)


def _read_frame(ser, timeout):
    """Collect one SOF..EOF frame, unescaping as we go.

    A mid-frame SOF means the previous frame was truncated -- resync on the new
    one rather than returning a half-parsed message that protobuf may still
    decode into plausible nonsense.
    """
    end = time.time() + timeout
    buf, started, escaped = bytearray(), False, False
    while time.time() < end:
        c = ser.read(1)
        if not c:
            continue
        b = c[0]
        if not started:
            started = b == SOF
            continue
        if escaped:
            buf.append(b)
            escaped = False
        elif b == ESC:
            escaped = True
        elif b == EOF:
            # A bare SOF/EOF pair yields b"", and ParseFromString(b"") SUCCEEDS,
            # producing a default Response that reads as an empty keymap. Keep
            # waiting instead of handing back a frame that says nothing.
            if buf:
                return bytes(buf)
        elif b == SOF:
            # escaped must reset too: a frame truncated right after an ESC left
            # this set, so the next SOF was swallowed as literal data and the
            # following frame appended to a stale buffer.
            buf.clear()
            escaped = False
        else:
            buf.append(b)
    return None


def _call(ser, request, timeout=5.0, expect=None):
    """Send one request; return only a response that actually answers it.

    Every field access on a proto3 message succeeds: an unset submessage yields
    a default instance. So a device error, a notification landing in the read
    window, or an empty frame all used to arrive as `Keymap` with zero layers,
    and the page rendered that as "source and board agree". A read that obtained
    nothing has to be distinguishable from a board that matches.

    ZMK raises core.lock_state_changed on every lock transition -- i.e. exactly
    when the user presses the unlock chord the UI asked for -- so notifications
    are not an edge case; they are skipped and the read continues.

    `expect` is "<subsystem>.<response_type>", e.g. "keymap.get_keymap".
    """
    ser.reset_input_buffer()
    ser.write(_frame(request.SerializeToString()))
    ser.flush()
    deadline = time.time() + timeout
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise RpcError("no_response",
                           "The keyboard did not answer. Is the left half connected?")
        raw = _read_frame(ser, left)
        if raw is None:
            raise RpcError("no_response",
                           "The keyboard did not answer. Is the left half connected?")
        resp = studio_pb2.Response()
        try:
            resp.ParseFromString(raw)
        except Exception as e:
            raise RpcError("protocol", f"Unreadable reply from the keyboard: {e}")

        kind = resp.WhichOneof("type")
        if kind == "notification":
            continue                      # volunteered by the board; not our answer
        if kind != "request_response":
            raise RpcError("protocol", "The keyboard sent a reply of an unknown kind.")

        rr = resp.request_response
        if rr.request_id != request.request_id:
            continue                      # a late answer to an earlier request
        sub_name = rr.WhichOneof("subsystem")
        if sub_name == "meta":
            code = rr.meta.simple_error
            try:
                code = meta_pb2.ErrorConditions.Name(code)
            except Exception:
                pass
            raise RpcError("device_error", f"The keyboard refused the request: {code}")
        if expect:
            want_sub, want_call = expect.split(".")
            if sub_name != want_sub:
                raise RpcError("protocol",
                               f"Expected a {want_sub} reply, got {sub_name or 'nothing'}.")
            got = getattr(rr, sub_name).WhichOneof("response_type")
            if got != want_call:
                raise RpcError("protocol",
                               f"Expected {want_call}, got {got or 'nothing'}.")
        return resp


def _open(port):
    try:
        # write_timeout defaults to None in pyserial, i.e. block forever. A half
        # unplugged after the port opened hung the request thread holding the
        # port, with the button stuck on "Reading..." until the server restarted.
        return serial.Serial(port, 115200, timeout=0.2, write_timeout=10)
    except SerialException as e:
        if "Resource busy" in str(e) or "Errno 16" in str(e):
            raise RpcError("busy", "Another program holds the port -- disconnect zmk.studio.")
        raise RpcError("no_port", f"Cannot open {port}: {e}")


def lock_state(ser):
    q = studio_pb2.Request(request_id=1)
    q.core.get_lock_state = True
    resp = _call(ser, q, expect="core.get_lock_state")
    return core_pb2.LockState.Name(resp.request_response.core.get_lock_state)


def _param_descs(details, which):
    """Full descriptors for a parameter slot: [{kind, name, constant}].

    The name matters: &mkp takes a constant whose display text ("LCLK") exists
    only here. Keeping just the kind would leave the renderer holding a bare
    integer with no way to spell it, and every mouse key would read as an edit.
    """
    out, seen = [], set()
    for pset in details.metadata:
        for desc in getattr(pset, which):
            kind = desc.WhichOneof("value_type")
            if not kind:
                continue
            item = {"kind": kind, "name": desc.name,
                    "constant": desc.constant if kind == "constant" else None}
            sig = (item["kind"], item["name"], item["constant"])
            if sig not in seen:
                seen.add(sig)
                out.append(item)
    return out


def read_behaviors(ser):
    """behavior_id -> {name, param1, param2}.

    The keymap gives only numeric behaviour ids. list_all_behaviors enumerates
    them and get_behavior_details names each and describes its parameters, so
    how to render a param is read off the device rather than assumed.
    """
    q = studio_pb2.Request(request_id=10)
    q.behaviors.list_all_behaviors = True
    ids = list(_call(ser, q, expect="behaviors.list_all_behaviors")
               .request_response.behaviors.list_all_behaviors.behaviors)
    if not ids:
        # An empty table renders every key as "unnameable", which the legend
        # tells the user is "Not a difference" -- a total protocol failure
        # reading as a healthy board.
        raise RpcError("protocol", "The keyboard listed no behaviours.")

    out = {}
    for n, bid in enumerate(ids):
        q = studio_pb2.Request(request_id=100 + n)
        q.behaviors.get_behavior_details.behavior_id = bid
        d = (_call(ser, q, expect="behaviors.get_behavior_details")
             .request_response.behaviors.get_behavior_details)
        out[bid] = {"name": d.display_name,
                    "param1": _param_descs(d, "param1"),
                    "param2": _param_descs(d, "param2")}
    return out


def read_board(port):
    """One pass over the wire: lock check, keymap, and the behaviour table."""
    with _open(port) as ser:
        time.sleep(0.3)
        if lock_state(ser) != UNLOCKED:
            raise RpcError("locked",
                           "The keyboard is locked. Press the unlock chord to continue.")
        q = studio_pb2.Request(request_id=2)
        q.keymap.get_keymap = True
        km = (_call(ser, q, timeout=10.0, expect="keymap.get_keymap")
              .request_response.keymap.get_keymap)
        if not km.layers:
            raise RpcError("protocol", "The keyboard returned a keymap with no layers.")
        return km, read_behaviors(ser)
