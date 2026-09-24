"""Parse the ZMK keymap into Vial-style labels plus the board's physical layout.

Labels follow QMK/Vial naming (MO(1), LT 2, MS_LEFT, MS_BTN1) so the rendered
keymap reads the same way the Vial GUI would show it.
"""
import re

import layout as layout_mod

BASIC = {
    "ESC":"Esc","TAB":"Tab","RET":"Enter","ENTER":"Enter","BSPC":"Bksp","DEL":"Del",
    "SPACE":"Space","CAPS":"Caps","HOME":"Home","END":"End","PG_UP":"PgUp","PG_DN":"PgDn",
    "UP":"↑","DOWN":"↓","LEFT":"←","RIGHT":"→",
    "LCTRL":"LCtrl","RCTRL":"RCtrl","LSHFT":"LShft","RSHFT":"RShift","LALT":"LAlt","RALT":"RAlt",
    "LGUI":"LGui","RGUI":"RGui",
    "SEMI":";","SQT":"'","COMMA":",","DOT":".","FSLH":"/","BSLH":"\\","MINUS":"-","EQUAL":"=",
    "LBKT":"[","RBKT":"]","GRAVE":"`",
    "KP_PLUS":"+","KP_MULTIPLY":"*","KP_DIVIDE":"/","KP_EQUAL":"=","KP_ENTER":"Enter",
    "K_UNDO":"Undo","K_CUT":"Cut","K_COPY":"Copy","K_PASTE":"Paste","K_AGAIN":"Again",
}
SHIFTED = {"N1":"!","N2":"@","N3":"#","N4":"$","N5":"%","N6":"^","N7":"&","N8":"*","N9":"(",
           "N0":")","SEMI":":","MINUS":"_","EQUAL":"+","LBKT":"{","RBKT":"}","SQT":'"',
           "COMMA":"<","DOT":">","FSLH":"?","BSLH":"|","GRAVE":"~"}
MODS = {"LS":"LSft","RS":"RSft","LC":"LCtl","RC":"RCtl","LA":"LAlt","RA":"RAlt",
        "LG":"LGui","RG":"RGui"}
MOUSE_BTN = {"LCLK":"MS_BTN1","RCLK":"MS_BTN2","MCLK":"MS_BTN3"}
MOUSE_DIR = {"UP":"MS_UP","DOWN":"MS_DOWN","LEFT":"MS_LEFT","RIGHT":"MS_RGHT"}


def kc(tok):
    """A single &kp argument -> display text."""
    m = re.fullmatch(r"(\w\w)\((.+)\)", tok)
    if m and m.group(1) in MODS:
        mod, inner = MODS[m.group(1)], m.group(2)
        if m.group(1) in ("LS", "RS") and inner in SHIFTED:
            return SHIFTED[inner]
        return f"{mod}+{kc(inner)}"
    if tok in BASIC:
        return BASIC[tok]
    if re.fullmatch(r"N\d", tok):
        return tok[1]
    if re.fullmatch(r"F\d{1,2}", tok):
        return tok
    if len(tok) == 1:
        return tok
    return tok


def label(binding, speeds):
    """One ZMK binding -> (main, sub) display lines."""
    p = binding.split()
    b = p[0]
    if b == "&kp":
        t = kc(p[1])
        return (t, "")
    if b == "&mo":
        return (f"MO({p[1]})", "")
    if b == "&lt":
        return (f"LT {p[1]}", kc(p[2]))
    if b == "&to":
        return (f"TO({p[1]})", "")
    if b == "&tog":
        return (f"TG({p[1]})", "")
    if b == "&mkp":
        return (MOUSE_BTN.get(p[1], p[1]), "")
    if b == "&mmv":
        arg = p[1]
        d = arg.replace("MOVE_", "").replace("SLOW_", "")
        spd = speeds["slow"] if arg.startswith("SLOW_") else speeds["fast"]
        return (MOUSE_DIR.get(d, arg), str(spd))
    if b == "&msc":
        return ("MS_WHLU" if "UP" in p[1] else "MS_WHLD", "")
    if b == "&trans":
        return ("▽", "")
    if b == "&none":
        return ("∅", "")
    if b == "&soft_off":
        return ("Soft Off", "")
    if b == "&bootloader":
        return ("Boot", "")
    if b == "&td0":
        return ("Shift", "Caps")
    return (b.lstrip("&"), " ".join(p[1:]))


ROWS = [13, 15, 14, 6]          # bindings per visual row
LAYER_RE = r'(\w+) \{\s*display-name = "([^"]+)";\s*bindings = <\n(.*?)\n(\s*)>;'


def split_bindings(body):
    return [t for line in body.split("\n")
            for t in re.split(r"\s{2,}", line.strip()) if t]


def set_bindings(text, edits):
    """Apply [{layer, index, binding}] to the keymap source, preserving layout.

    ponytail: rewrites the whole row block rather than patching in place -- the
    columns have to be re-padded anyway once a token changes width."""
    for e in edits:
        m = None
        for cand in re.finditer(LAYER_RE, text, re.S):
            if cand.group(2) == e["layer"]:
                m = cand
                break
        if not m:
            raise ValueError(f"layer {e['layer']!r} not found")
        flat = split_bindings(m.group(3))
        if len(flat) != 48:
            raise ValueError(f"{e['layer']}: {len(flat)} bindings, expected 48")
        idx = int(e["index"])
        if not 0 <= idx < 48:
            raise ValueError(f"index {idx} out of range")
        flat[idx] = e["binding"].strip()
        width = max(len(t) for t in flat) + 2
        out, i = [], 0
        for n in ROWS:
            out.append("  " + "".join(t.ljust(width) for t in flat[i:i + n]).rstrip())
            i += n
        text = text[:m.start(3)] + "\n".join(out) + text[m.end(3):]
    return text


def parse(text, repo):
    """Keymap source -> layers, using geometry derived from the shield sources."""
    geo = layout_mod.analyse(repo)
    LAYOUT = [(x, y, r, rx, ry) for (x, y, w, h, r, rx, ry) in geo["physical"]]
    JOYSTICK, ROTARY = geo["joystick"], geo["rotary"]
    speeds = {"fast": 0, "slow": 0}
    m = re.search(r"#define ZMK_POINTING_DEFAULT_MOVE_VAL\s+(\d+)", text)
    if m: speeds["fast"] = int(m.group(1))
    m = re.search(r"#define ZMK_POINTING_SLOW_MOVE_VAL\s+(\d+)", text)
    if m: speeds["slow"] = int(m.group(1))

    layers = []
    for blk in re.finditer(LAYER_RE, text, re.S):
        _, name, body, _ = blk.groups()
        toks = split_bindings(body)
        if len(toks) != 48:
            continue
        line_no = text.count("\n", 0, blk.start()) + 1
        keys = []
        for i, t in enumerate(toks):
            main, sub = label(t, speeds)
            keys.append({"main": main, "sub": sub, "binding": t,
                         "joy": JOYSTICK.get(i), "rotary": i == ROTARY})
        layers.append({"name": name, "keys": keys, "line": line_no})
    return {"layers": layers, "speeds": speeds, "layout": LAYOUT}
