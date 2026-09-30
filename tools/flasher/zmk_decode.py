"""Translate between ZMK source bindings (`&kp LS(N1)`) and what the board reports.

The Studio RPC speaks BehaviorBinding{behavior_id, param1, param2} -- integers.
Source speaks `&kp Q`. Comparing the two needs a bridge, and a wrong bridge
silently rewrites the wrong key, so nothing here is hand-typed: every table is
parsed out of the ZMK checkout that built the firmware.

  keycodes      dt-bindings/zmk/keys.h, resolved through hid_usage.h and
                hid_usage_pages.h, where ZMK_HID_USAGE(page, id) = page<<16 | id
  modifiers     dt-bindings/zmk/modifiers.h, APPLY_MODS(m, kc) = m<<24 | kc
  behaviors     each app/dts/behaviors/*.dtsi carries both the node label used
                in source (`kp:`) and the display-name the RPC reports.

Run this file directly to check the tables against the committed keymap.
"""
import functools
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DTB = os.path.join(ROOT, "zmk", "app", "include", "dt-bindings", "zmk")
BEHAVIORS_DTS = os.path.join(ROOT, "zmk", "app", "dts", "behaviors")

MOD_BITS = {"LCTL": 0x01, "LSFT": 0x02, "LALT": 0x04, "LGUI": 0x08,
            "RCTL": 0x10, "RSFT": 0x20, "RALT": 0x40, "RGUI": 0x80}
# the source spellings that wrap a keycode, e.g. LS(N1)
MOD_FUNCS = {"LC": "LCTL", "LS": "LSFT", "LA": "LALT", "LG": "LGUI",
             "RC": "RCTL", "RS": "RSFT", "RA": "RALT", "RG": "RGUI"}

_DEFINE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+(.+?)\s*(?://.*)?$", re.M)


def _defines(*names):
    out = {}
    for n in names:
        path = n if os.path.isabs(n) else os.path.join(DTB, n)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        text = re.sub(r"\\\s*\n\s*", " ", text)   # keys.h wraps long defines
        for m in _DEFINE.finditer(text):
            key, val = m.group(1), m.group(2).strip()
            if key.endswith(")") or "(" in m.group(0).split(key, 1)[1][:1]:
                continue  # function-like macro, handled separately
            out.setdefault(key, val)
    return out


@functools.lru_cache(maxsize=1)
def _raw():
    return _defines("hid_usage_pages.h", "hid_usage.h", "keys.h")


@functools.lru_cache(maxsize=1)
def _params():
    """Names defined by the headers that are NOT keycodes.

    `&mmv MOVE_UP` and `&bt BT_SEL` are legal bindings whose parameters live in
    pointing.h and bt.h, so known_keycode() -- which only reads keys.h -- says
    False for both. Checking those against keys.h would reject the keymap's own
    working bindings.

    The keymap is scanned last for the same reason behaviors() scans it: this
    one #defines SLOW_UP/SLOW_DOWN/SLOW_LEFT/SLOW_RIGHT and binds them with
    &mmv, and no upstream header has ever heard of them.
    """
    return _defines("pointing.h", "mouse.h", "bt.h", "rgb.h", "outputs.h",
                    "ext_power.h", "backlight.h", "reset.h",
                    os.path.join(ROOT, "config", "eyelash_corne.keymap"))


def known_param(text):
    """True when ZMK defines this name anywhere dtc will resolve it.

    Same question as known_keycode, widened past keys.h: not "what integer is
    this" but "will the build accept the symbol".
    """
    t = (text or "").strip()
    if not t:
        return False
    return t in _params() or known_keycode(t)


def _resolve(expr, seen=()):
    """Evaluate a keys.h right-hand side to an int, or None if not a keycode."""
    e = expr.strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    m = re.fullmatch(r"ZMK_HID_USAGE\s*\(\s*([^,]+?)\s*,\s*(.+?)\s*\)", e)
    if m:
        page, usage = _resolve(m.group(1), seen), _resolve(m.group(2), seen)
        if page is None or usage is None:
            return None
        return (page << 16) | usage
    m = re.fullmatch(r"BIT\s*\(\s*(\d+)\s*\)", e)
    if m:
        return 1 << int(m.group(1))
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", e):
        return int(e, 16)
    if re.fullmatch(r"\d+", e):
        return int(e)
    if re.fullmatch(r"[A-Za-z_]\w*", e):
        if e in seen:
            return None                      # cyclic alias
        val = _raw().get(e)
        return _resolve(val, seen + (e,)) if val is not None else None
    return None


def _balanced(s):
    d = 0
    for c in s:
        d += (c == "(") - (c == ")")
        if d < 0:
            return False
    return d == 0


@functools.lru_cache(maxsize=1)
def constants():
    """name -> int for non-keycode binding params, e.g. mouse buttons.

    &mkp takes LCLK, which pointing.h defines as MB1, which is BIT(0). The
    device reports whichever spelling its metadata carries, so both have to
    resolve to the same number or one key reads as an edit nobody made.
    """
    out = {}
    for name, expr in _pointing_defines().items():
        v = _resolve_pointing(name, expr)
        if v is not None:
            out[name] = v
    return out


@functools.lru_cache(maxsize=1)
def _pointing_defines():
    """pointing.h's names, with THIS keymap's overrides taking precedence.

    pointing.h guards its defaults with #ifndef and the keymap sets
    ZMK_POINTING_DEFAULT_MOVE_VAL to 1200 before including it, so the board
    packs MOVE_UP from 1200 and not the header's 600. _defines keeps the first
    definition it sees, so the keymap must come first -- otherwise every
    pointer key resolves to the wrong integer and reads as an edit nobody made.
    It also carries SLOW_UP and friends, which exist in no upstream header.
    """
    return _defines(os.path.join(ROOT, "config", "eyelash_corne.keymap"),
                    "pointing.h")


def _resolve_pointing(name, expr, seen=()):
    # the keymap writes its values with trailing // comments
    e = re.split(r"/[/*]", expr, 1)[0].strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    m = re.fullmatch(r"BIT\s*\(\s*(\d+)\s*\)", e)
    if m:
        return 1 << int(m.group(1))
    # MOVE_X/MOVE_Y pack a signed 16-bit delta; &mmv and &msc carry the result.
    # Without this the source spelling stayed a string and could never equal the
    # integer the board reports, so all ten pointer keys read as changed.
    m = re.fullmatch(r"(MOVE_X|MOVE_Y)\s*\((.+)\)", e)
    if m:
        inner = _resolve_pointing(name, m.group(2), seen)
        if inner is None:
            return None
        packed = inner & 0xFFFF
        return (packed << 16) if m.group(1) == "MOVE_X" else packed
    if e.startswith("-"):
        v = _resolve_pointing(name, e[1:], seen)
        return None if v is None else -v
    if re.fullmatch(r"\d+", e):
        return int(e)
    if re.fullmatch(r"[A-Za-z_]\w*", e) and e not in seen:
        nxt = _pointing_defines().get(e)
        if nxt is not None:
            return _resolve_pointing(e, nxt, seen + (e,))
    return None


@functools.lru_cache(maxsize=1)
def keycodes():
    """name -> int, for every keycode spelling keys.h offers."""
    out = {}
    for name, expr in _raw().items():
        if name.startswith(("HID_USAGE", "ZMK_HID_USAGE", "MOD_")):
            continue
        v = _resolve(expr)
        if v is not None and v >> 16:        # has a usage page; a bare number is not a keycode
            out[name] = v
    return out


@functools.lru_cache(maxsize=1)
def _by_value():
    """int -> preferred name. Shortest wins, so N1 beats NUMBER_1 and A beats nothing."""
    best = {}
    for name, v in keycodes().items():
        cur = best.get(v)
        if cur is None or (len(name), name) < (len(cur), cur):
            best[v] = name
    return best


def encode_keycode(text):
    """`LS(N1)` -> int, or None if any part is unknown."""
    t = text.strip()
    m = re.fullmatch(r"([A-Z]{2})\s*\((.*)\)", t)
    if m and m.group(1) in MOD_FUNCS:
        inner = encode_keycode(m.group(2))
        return None if inner is None else (MOD_BITS[MOD_FUNCS[m.group(1)]] << 24) | inner
    return keycodes().get(t)


@functools.lru_cache(maxsize=None)
def encode_alias(name):
    """A keys.h alias -> the integer the board reports, or None.

    EXCL is defined as LS(N1): it has no HID usage of its own, so
    encode_keycode() returns None for it. The board reports the modified value
    and decodes back to "LS(N1)", which could never equal the source spelling
    "EXCL" -- so that key read as changed on every single read, forever.
    Follow the #define chain, applying modifier wrappers as they appear.
    """
    expr = _raw().get(name)
    return None if expr is None else _resolve_modded(expr)


def _resolve_modded(expr, depth=0):
    if depth > 8:
        return None
    e = expr.strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    m = re.fullmatch(r"([A-Z]{2})\s*\((.*)\)", e)
    if m and m.group(1) in MOD_FUNCS:
        inner = _resolve_modded(m.group(2), depth + 1)
        return None if inner is None else (MOD_BITS[MOD_FUNCS[m.group(1)]] << 24) | inner
    v = _resolve(e)
    if v is not None:
        return v
    nxt = _raw().get(e)
    return _resolve_modded(nxt, depth + 1) if nxt is not None else None


def known_keycode(text):
    """True when ZMK's headers define this keycode spelling, so dtc compiles it.

    Deliberately not encode_keycode(): that answers "which integer is this" and
    returns None for EXCL -- a real keycode defined as LS(N1), with no HID usage
    of its own. The only question here is whether the build will accept it.
    """
    t = (text or "").strip()
    if not t:
        return False
    m = re.fullmatch(r"([A-Z]{2})\s*\((.*)\)", t)
    if m and m.group(1) in MOD_FUNCS:
        return known_keycode(m.group(2))
    return t in _raw()


def decode_keycode(value):
    """int -> `LS(N1)`, or None if the base usage is not one we know."""
    mods, base = (value >> 24) & 0xFF, value & 0x00FFFFFF
    name = _by_value().get(base)
    if name is None:
        return None
    for short, bit in MOD_FUNCS.items():
        if mods == MOD_BITS[bit]:
            return f"{short}({name})"
    if mods:                                  # several modifiers at once: nest them
        out = name
        for short, bit in MOD_FUNCS.items():
            if mods & MOD_BITS[bit]:
                out = f"{short}({out})"
        return out
    return name


@functools.lru_cache(maxsize=1)
def behaviors():
    """devicetree label -> the display_name the RPC will report.

    ZMK uses DT_PROP_OR(node, display_name, DEVICE_DT_NAME(node)) (see
    drivers/behavior.h), so a behaviour with no display-name property reports
    its node name instead -- `mmv: mouse_move` comes back as "mouse_move".
    Mirroring that fallback here is what makes mmv/msc/soft_off resolvable.

    The user's own keymap is scanned too, for behaviours defined locally
    (tap dances, sensor rotates) that exist in no upstream dtsi.
    """
    out = {}
    node = re.compile(r"(\w+)\s*:\s*(\w+)\s*\{(.*?)\n\s*\};", re.S)
    sources = []
    if os.path.isdir(BEHAVIORS_DTS):
        sources += [os.path.join(BEHAVIORS_DTS, f)
                    for f in sorted(os.listdir(BEHAVIORS_DTS)) if f.endswith(".dtsi")]
    sources.append(os.path.join(ROOT, "config", "eyelash_corne.keymap"))
    for path in sources:
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        for m in node.finditer(text):
            label, node_name, body = m.group(1), m.group(2), m.group(3)
            if "compatible" not in body:
                continue                      # not a behaviour node
            dn = re.search(r'display-name\s*=\s*"([^"]+)"', body)
            out.setdefault(label, dn.group(1) if dn else node_name)
    return out


def label_for_display_name(display_name):
    for label, dn in behaviors().items():
        if dn == display_name:
            return label
    return None


if __name__ == "__main__":
    import sys
    kc, bh = keycodes(), behaviors()
    print(f"{len(kc)} keycodes, {len(bh)} behaviours parsed")
    assert kc.get("Q") == (0x07 << 16) | 0x14, kc.get("Q")
    assert encode_keycode("LS(N1)") == (0x02 << 24) | keycodes()["N1"]
    assert decode_keycode(encode_keycode("LS(N1)")) == "LS(N1)"
    assert decode_keycode(kc["Q"]) == "Q"
    assert bh.get("kp") == "Key Press", bh.get("kp")
    assert label_for_display_name("Momentary Layer") == "mo"

    # every keycode the committed keymap actually uses must round-trip
    src = open(os.path.join(ROOT, "config", "eyelash_corne.keymap"),
               encoding="utf-8").read()
    used = set()
    for m in re.finditer(r"&kp\s+", src):
        i = m.end()
        j, depth = i, 0
        while j < len(src):
            c = src[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            elif depth == 0 and not (c.isalnum() or c == "_"):
                break
            j += 1
        used.add(src[i:j].strip())
    bad = []
    for t in sorted(used):
        v = encode_keycode(t)
        if v is None or decode_keycode(v) is None:
            bad.append(t)
    print(f"keymap uses {len(used)} distinct keycodes; {len(bad)} fail to round-trip")
    if bad:
        print("  FAIL:", ", ".join(bad))
        sys.exit(1)
    used_b = set(re.findall(r"&(\w+)", src))
    unmapped = sorted(b for b in used_b if b not in bh)
    print(f"keymap uses {len(used_b)} behaviours; {len(unmapped)} unmapped")
    if unmapped:
        print("  FAIL:", ", ".join(unmapped))
        sys.exit(1)
    print("all round-trip OK")
