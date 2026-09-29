"""Self-check for binding validation. Run: python3 test_bindings.py

A binding that ZMK cannot compile must never reach the keymap: workflow() pushes
the predeploy tag before it builds, so the break lands on main and is only found
when the Docker build fails.
"""
import keymap as k

KEYMAP = "../../config/eyelash_corne.keymap"


def main():
    # Rejected: the typo that started this, and a behaviour that does not exist.
    assert k.why_invalid("&kp NOT_A_KEY"), "a bogus keycode must be refused"
    assert k.why_invalid("&kp ZZZZZ"), "a bogus keycode must be refused"
    assert k.why_invalid("&kp LS(ZZZZZ)"), "a bogus keycode inside a modifier too"
    assert k.why_invalid("&k A"), "a half-typed behaviour must be refused"
    assert k.why_invalid("&kp"), "&kp with no keycode must be refused"
    assert k.why_invalid("&kp A B"), "&kp with two keycodes must be refused"
    assert k.why_invalid(""), "an empty binding must be refused"

    # Accepted: EXCL is the trap. It is a real keycode defined as LS(N1), so it
    # has no HID usage of its own and encode_keycode() returns None for it --
    # validating with that would reject a whole class of legitimate keys.
    for good in ("&kp A", "&kp EXCL", "&kp AT", "&kp DQT", "&kp PLUS", "&kp UNDER",
                 "&kp LS(SQT)", "&kp LS(LG(UP))", "&trans", "&mo 1", "&lt 2 SPACE",
                 "&mmv MOVE_UP", "&mkp LCLK", "&msc SCRL_UP"):
        assert not k.why_invalid(good), f"{good} is valid and must be accepted"

    # The preview path and the write path must agree, or the editor refuses what
    # the keymap would have taken, or worse, the reverse.
    assert k.to_binding("&kp ZZZZZ") is None
    assert k.to_binding("&kp EXCL") == "&kp EXCL"
    assert k.to_binding("=") == "&kp EQUAL"

    # Nothing already in the keymap may be refused: clicking a key prefills its
    # current binding, so a false negative would block re-applying it unchanged.
    src = open(KEYMAP).read()
    d = k.parse(src, "../..")
    for layer in d["layers"]:
        for i, key in enumerate(layer["keys"]):
            why = k.why_invalid(key["binding"])
            assert not why, f"{layer['name']}[{i}] {key['binding']!r} rejected: {why}"

    # The write path refuses too, not just the preview.
    try:
        k.set_bindings(src, [{"layer": "NAV", "index": 36, "binding": "&kp ZZZZZ"}])
        raise AssertionError("set_bindings wrote a binding ZMK cannot compile")
    except ValueError as e:
        assert "not a keycode" in str(e), e

    # and still writes a good one
    out = k.set_bindings(src, [{"layer": "NAV", "index": 36, "binding": "&kp EXCL"}])
    assert "&kp EXCL" in out

    print("ok: binding validation holds on both the preview and the write path")


if __name__ == "__main__":
    main()
