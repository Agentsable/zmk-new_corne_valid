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

from zmk_proto import behaviors_pb2, core_pb2, keymap_pb2, studio_pb2  # noqa: F401  (registers types)

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
            return bytes(buf)
        elif b == SOF:
            buf.clear()
        else:
            buf.append(b)
    return None


def _call(ser, request, timeout=5.0):
    ser.reset_input_buffer()
    ser.write(_frame(request.SerializeToString()))
    ser.flush()
    raw = _read_frame(ser, timeout)
    if raw is None:
        raise RpcError("no_response", "The keyboard did not answer. Is the left half connected?")
    resp = studio_pb2.Response()
    resp.ParseFromString(raw)
    return resp


def _open(port):
    try:
        return serial.Serial(port, 115200, timeout=0.2)
    except SerialException as e:
        if "Resource busy" in str(e) or "Errno 16" in str(e):
            raise RpcError("busy", "Another program holds the port -- disconnect zmk.studio.")
        raise RpcError("no_port", f"Cannot open {port}: {e}")


def lock_state(ser):
    q = studio_pb2.Request(request_id=1)
    q.core.get_lock_state = True
    resp = _call(ser, q)
    return core_pb2.LockState.Name(resp.request_response.core.get_lock_state)


def read_keymap(port, unlock_wait=0.0):
    """Return the board's keymap as a protobuf message.

    `unlock_wait` seconds are spent polling for the user to press the unlock
    chord; 0 means fail immediately so a UI can ask rather than hang.
    """
    with _open(port) as ser:
        time.sleep(0.3)
        state = lock_state(ser)
        if state != UNLOCKED:
            deadline = time.time() + unlock_wait
            while time.time() < deadline and state != UNLOCKED:
                time.sleep(1.0)
                state = lock_state(ser)
        if state != UNLOCKED:
            raise RpcError("locked", "The keyboard is locked. Press the unlock chord to continue.")
        q = studio_pb2.Request(request_id=2)
        q.keymap.get_keymap = True
        resp = _call(ser, q, timeout=10.0)
        return resp.request_response.keymap.get_keymap


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
    ids = list(_call(ser, q).request_response.behaviors.list_all_behaviors.behaviors)

    out = {}
    for n, bid in enumerate(ids):
        q = studio_pb2.Request(request_id=100 + n)
        q.behaviors.get_behavior_details.behavior_id = bid
        d = _call(ser, q).request_response.behaviors.get_behavior_details
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
        km = _call(ser, q, timeout=10.0).request_response.keymap.get_keymap
        return km, read_behaviors(ser)
