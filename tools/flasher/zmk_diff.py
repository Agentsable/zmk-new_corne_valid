"""Compare the keymap on the board against the committed source, per key.

The board reports integers; source is text. zmk_decode bridges the two, and
this module decides which keys actually differ. Rendering the board side as
source text (rather than diffing integers) means an adopted change can be
written straight back with keymap.set_bindings, and means a human can read
what is being proposed.

A binding we cannot render is reported as unknown rather than as a difference:
claiming a key changed when the decoder simply does not know it would send the
user to adopt a change that does not exist.
"""
import re

import zmk_decode


def binding_to_source(behavior_id, param1, param2, behaviors):
    """One BehaviorBinding -> `&kp LS(N1)`, or None if it cannot be rendered.

    Parameter meaning comes from the device's own metadata: a hid_usage slot is
    a keycode, a layer_id slot is a layer index. Nothing is inferred from the
    behaviour's name.
    """
    info = behaviors.get(behavior_id)
    if not info:
        return None
    label = zmk_decode.label_for_display_name(info["name"])
    if label is None:
        return None
    parts = ["&" + label]
    slots = [([d for d in info.get(slot, []) if d.get("kind") != "nil"], val)
             for slot, val in (("param1", param1), ("param2", param2))]
    # Trailing empty slots are simply absent parameters. An empty slot with a
    # populated one AFTER it is different: appending positionally promoted
    # param2 into param1's place and rendered "&my_ht Q" for "&my_ht 0 Q" -- a
    # false diff whose adopted form does not build. Reachable through hold-taps
    # whose hold child carries empty metadata (&trans, &caps_word, &soft_off).
    while slots and not slots[-1][0]:
        slots.pop()
    for descs, val in slots:
        if not descs:
            return None          # cannot place the parameters; unknown, not wrong
        text = _render_param(descs, val)
        if text is None:
            return None          # unnameable param -> unknown, not a false change
        parts.append(text)
    return " ".join(parts)


def _render_param(descs, val):
    """Spell one parameter, or None if the device gave us no way to name it."""
    for d in descs:
        if d["kind"] == "constant" and d.get("constant") == val:
            return d["name"] or str(val)
    kinds = {d["kind"] for d in descs}
    if "hid_usage" in kinds:
        return zmk_decode.decode_keycode(val)
    if "layer_id" in kinds:
        return str(val)
    if "range" in kinds:
        # &mmv and &msc are input_two_axis, whose param1 the firmware declares
        # as RANGE ("X Y", 0..UINT32_MAX). It was unhandled, so all ten pointer
        # keys fell through to None and the page called them "unnameable" --
        # which the legend tells the reader is "Not a difference". It is a
        # plain integer; spell it and it compares like anything else.
        return str(val)
    if kinds == {"constant"}:
        return None              # a constant slot with no matching value
    return None


def _norm(binding):
    return re.sub(r"\s+", " ", (binding or "").strip())


def _canon(text):
    """Reduce a binding to (label, resolved params) for comparison.

    Text comparison is wrong here. RCTRL and RCTL are one keycode spelled two
    ways, and LS(LG(UP)) and LG(LS(UP)) are one set of modifier bits in two
    orders -- both would read as edits the user never made. Resolving params to
    their integer values collapses every alias and ordering to one form.
    """
    toks = _norm(text).split()
    if not toks:
        return None
    vals = []
    for tok in toks[1:]:
        v = zmk_decode.encode_keycode(tok)
        if v is None:
            # non-keycode params: mouse buttons and friends, where LCLK and MB1
            # are one value under two names, exactly like RCTRL and RCTL
            v = zmk_decode.constants().get(tok)
        if v is None:
            # keys.h aliases like EXCL resolve to LS(N1) and encode_keycode
            # returns None for them, so the board's decoded LS(N1) could never
            # match the source spelling and that key read as changed forever.
            v = zmk_decode.encode_alias(tok)
        if v is None:
            v = int(tok) if tok.lstrip("-").isdigit() else tok
        vals.append(v)
    return (toks[0].lstrip("&"), tuple(vals))


def _same(a, b):
    ca, cb = _canon(a), _canon(b)
    if ca is None or cb is None:
        return _norm(a) == _norm(b)
    return ca == cb


def diff(source_layers, board_layers, behaviors, rejected=()):
    """Per-layer, per-position comparison.

    `rejected` holds "layer/index" keys the user has already declined; those
    keep their diff visible as a decision but are not counted as outstanding,
    and the UI stops marking them on the source side.
    """
    rejected = set(rejected)
    # Pair by NAME where both sides name their layers uniquely. Position pairing
    # broke the moment a layer moved in Studio -- move_layer is a supported RPC
    # -- and every key in the moved layers then read as changed, with adopting
    # one writing the wrong binding into the wrong layer. Names travel with the
    # layer; array position does not.
    by_name, dupes = {}, set()
    for L in source_layers:
        n = L.get("name")
        if n in by_name:
            dupes.add(n)
        by_name[n] = L
    board_names = [b.get("name") for b in board_layers]
    use_names = (not dupes
                 and len(set(board_names)) == len(board_names)
                 and all(n in by_name for n in board_names if n))

    out = []
    used = set()
    for i, board in enumerate(board_layers):
        if use_names and board.get("name") in by_name:
            src = by_name[board["name"]]
            used.add(id(src))
        else:
            src = source_layers[i] if i < len(source_layers) else None
        # A layer the board has and source does not used to force changed=False
        # for every key, so a layer added in Studio rendered "in sync" -- the
        # exact case this page exists to catch.
        extra_layer = src is None
        keys = []
        # Compare the union: iterating only the board's bindings silently
        # dropped any position a truncated layer failed to report, and the grid
        # still looked complete.
        width = max(len(board.get("bindings", [])), len(src["keys"]) if src else 0)
        for j in range(width):
            blist = board.get("bindings", [])
            b = blist[j] if j < len(blist) else None
            s_txt = src["keys"][j]["binding"] if src and j < len(src["keys"]) else None
            b_txt = (binding_to_source(b.get("behavior_id", 0), b.get("param1", 0),
                                       b.get("param2", 0), behaviors)
                     if b is not None else None)
            key = f"{i}/{j}"
            missing = b is None
            unknown = b_txt is None and not missing
            if missing:
                # the board never reported this position
                changed = s_txt is not None
            elif extra_layer:
                # nothing to compare against: the whole layer is new on the board
                changed = b_txt is not None
            else:
                changed = (not unknown) and s_txt is not None and not _same(s_txt, b_txt)
            if not changed and not unknown:
                b_txt = s_txt      # same key, different spelling: show one form
            keys.append({
                "index": j,
                "source": s_txt,
                "board": b_txt,
                "changed": changed,
                "unknown": unknown,
                "missing": missing,
                "rejected": key in rejected,
            })
        out.append({
            "index": i,
            "source_name": src["name"] if src else None,
            "board_name": board.get("name") or f"Layer {i}",
            "paired_by": "name" if use_names else "position",
            "keys": keys,
            "changed": sum(1 for k in keys if k["changed"] and not k["rejected"]),
            "unknown": sum(1 for k in keys if k["unknown"]),
        })
    return out


if __name__ == "__main__":
    import os
    import sys

    import keymap as keymap_mod

    ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    src = keymap_mod.parse(open(os.path.join(ROOT, "config", "eyelash_corne.keymap")).read(), ROOT)
    layers = src["layers"]

    # Synthesise a board that agrees with source exactly, by running the bridge
    # forwards. If the round trip is sound this must produce zero differences.
    beh, ids = {}, {}
    def _add(lst, item):
        if item not in lst:
            lst.append(item)

    def bid(label):
        if label not in ids:
            ids[label] = len(ids) + 1
            beh[ids[label]] = {"name": zmk_decode.behaviors()[label],
                               "param1": [], "param2": []}
        return ids[label]

    board = []
    for L in layers:
        bs = []
        for k in L["keys"]:
            toks = k["binding"].split()
            label = toks[0].lstrip("&")
            if label not in zmk_decode.behaviors():
                bs.append({"behavior_id": 0, "param1": 0, "param2": 0})
                continue
            i = bid(label)
            p1 = p2 = 0
            if len(toks) > 1:
                v = zmk_decode.encode_keycode(toks[1])
                if v is not None:
                    _add(beh[i]["param1"], {"kind": "hid_usage", "name": "", "constant": None})
                    p1 = v
                elif toks[1].isdigit():
                    _add(beh[i]["param1"], {"kind": "layer_id", "name": "", "constant": None})
                    p1 = int(toks[1])
                else:
                    # &mkp LCLK style: the device names the constant
                    const = abs(hash(toks[1])) % 60000
                    _add(beh[i]["param1"], {"kind": "constant", "name": toks[1],
                                            "constant": const})
                    p1 = const
            if len(toks) > 2:            # &lt 2 SPACE
                v2 = zmk_decode.encode_keycode(toks[2])
                if v2 is not None:
                    _add(beh[i]["param2"], {"kind": "hid_usage", "name": "", "constant": None})
                    p2 = v2
            bs.append({"behavior_id": i, "param1": p1, "param2": p2})
        board.append({"name": L["name"], "bindings": bs})

    d = diff(layers, board, beh)
    changed = sum(x["changed"] for x in d)
    unknown = sum(x["unknown"] for x in d)
    print(f"identical board: {changed} changed, {unknown} unrenderable")
    if changed:
        for L in d:
            for k in L["keys"]:
                if k["changed"]:
                    print(f"   L{L['index']}/{k['index']}: src={k['source']!r} board={k['board']!r}")

    assert changed == 0, "a board equal to source must show no changes"

    # now mutate one key and confirm exactly one difference surfaces
    board[0]["bindings"][1] = {"behavior_id": bid("kp"),
                               "param1": zmk_decode.encode_keycode("Z"), "param2": 0}
    d2 = diff(layers, board, beh)
    hits = [(L["index"], k["index"], k["source"], k["board"])
            for L in d2 for k in L["keys"] if k["changed"]]
    print("after mutating layer0 key1:", hits)
    assert len(hits) == 1 and hits[0][:2] == (0, 1), hits
    assert hits[0][3] == "&kp Z", hits

    # and that rejecting it clears the outstanding count
    d3 = diff(layers, board, beh, rejected={"0/1"})
    assert sum(x["changed"] for x in d3) == 0, "rejected keys must not stay outstanding"
    print("diff, mutation and rejection all behave")
