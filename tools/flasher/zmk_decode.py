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
        path = os.path.join(DTB, n)
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
