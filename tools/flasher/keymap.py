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
    alias = _expand_alias(tok)
    if alias:
        return kc(alias)
    return tok


def _expand_alias(tok):
    """EXCL -> "LS(N1)", so the shifted-symbol path above can spell it as "!".

    keys.h defines a whole family of these (EXCL, AT, DQT, PIPE, ...). They were
    falling through to the raw name, so a key bound to &kp EXCL rendered as
    "EXCL" on the board diagram. Expanded from the header rather than a second
    hand-written table, which would drift.
    """
    try:
        import zmk_decode
    except Exception:
        return None
    v = zmk_decode.encode_alias(tok)
    if v is None:
        return None
    back = zmk_decode.decode_keycode(v)
    return back if back and back != tok else None


def label(binding, speeds):
    """One ZMK binding -> (main, sub) display lines.

    Tolerates a binding that is missing its parameters. The live preview calls
    this on every keystroke, so it sees "&kp" long before it sees "&kp A", and
    an IndexError there took the whole endpoint down.
    """
    p = binding.split()
    if not p:
        return ("", "")
    b = p[0]
    need = {"&kp": 2, "&mo": 2, "&lt": 3, "&to": 2, "&tog": 2,
            "&mkp": 2, "&mmv": 2, "&msc": 2}.get(b)
    if need and len(p) < need:
        return (b.lstrip("&"), "…")
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
        binding = e["binding"].strip()
        bad = why_invalid(binding)
        if bad:
            raise ValueError(f"{e['layer']}[{idx}]: {bad}")
        flat[idx] = binding
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
    # rc is the shield's own matrix (row, col); the coordinates view needs the
    # row from it rather than guessing from y, which column stagger makes unreliable.
    return {"layers": layers, "speeds": speeds, "layout": LAYOUT, "rc": geo["rc"]}


def _inverse_display():
    """Rendered text -> the keycode that produces it.

    Built by inverting the same BASIC and SHIFTED tables label() renders with,
    so what you can type is exactly what the board can show. First spelling
    wins, which keeps the common one ("=" -> EQUAL, not KP_EQUAL).
    """
    inv = {}
    # Keypad spellings last: "+" should mean shifted-equals on a 40% board, not
    # KP_PLUS, and "*" should mean LS(N8). They still resolve, just not first.
    for name, disp in BASIC.items():
        if not name.startswith("KP_"):
            inv.setdefault(disp, name)
    for name, disp in SHIFTED.items():
        inv.setdefault(disp, f"LS({name})")
    for name, disp in BASIC.items():
        inv.setdefault(disp, name)
    return inv


_INVERSE = None


# What each behaviour's parameters have to be, for the behaviours whose
# signature is knowable. Anything not listed is left alone on purpose.
#   key    a keycode keys.h defines          (&kp A, &mt LSHFT B)
#   layer  a layer index                     (&mo 1, &lt 2 SPACE)
#   name   a constant from the non-keycode headers (&mkp LCLK, &mmv MOVE_UP)
PARAMS = {
    "kp": ("key",), "sk": ("key",),
    "mo": ("layer",), "to": ("layer",), "tog": ("layer",), "sl": ("layer",),
    "lt": ("layer", "key"), "mt": ("key", "key"),
    "mkp": ("name",), "mmv": ("name",), "msc": ("name",),
    "trans": (), "none": (), "studio_unlock": (), "soft_off": (), "bootloader": (),
}


def why_invalid(binding):
    """None when ZMK will compile this binding, else a sentence saying why not.

    Both the live preview and the write path ask this, so what the editor
    refuses and what can reach the keymap cannot drift apart.

    Behaviours absent from PARAMS -- locally defined tap dances and sensor
    rotates, anything ZMK adds later -- pass on arity and parameters. Claiming
    to know a signature we do not would reject bindings that build fine.
    """
    parts = (binding or "").split()
    if not parts:
        return "empty binding"
    try:
        import zmk_decode
    except Exception:
        return None          # no ZMK checkout to check against; do not block
    known = zmk_decode.behaviors()
    name = parts[0].lstrip("&")
    if known and name not in known:
        return f"no behaviour called &{name}"
    spec = PARAMS.get(name)
    if spec is None:
        return None
    args = parts[1:]
    if len(args) != len(spec):
        return (f"&{name} takes {len(spec)} parameter"
                f"{'' if len(spec) == 1 else 's'}, got {len(args)}")
    for arg, kind in zip(args, spec):
        # Left unchecked any of these reaches the keymap, and workflow() pushes
        # the predeploy tag before it builds -- so the break lands on main first.
        if kind == "layer":
            if not re.fullmatch(r"\d+", arg):
                return f"&{name} needs a layer number, not {arg}"
        elif kind == "key":
            if not zmk_decode.known_keycode(arg):
                return f"{arg} is not a keycode ZMK defines"
        elif kind == "name":
            if not zmk_decode.known_param(arg):
                return f"{arg} is not a name ZMK defines"
    return None


def to_binding(text):
    """Free text -> a ZMK binding, or None if it cannot be resolved.

    Accepts what a person would actually type: a full binding, a rendered
    symbol, a bare keycode name, or a single letter or digit.
    """
    global _INVERSE
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("&"):
        binding = " ".join(t.split())
        return None if why_invalid(binding) else binding
    if _INVERSE is None:
        _INVERSE = _inverse_display()
    if t in _INVERSE:
        return f"&kp {_INVERSE[t]}"
    if len(t) == 1 and t.isalpha():
        return f"&kp {t.upper()}"
    if len(t) == 1 and t.isdigit():
        return f"&kp N{t}"
    try:
        import zmk_decode
        if zmk_decode.encode_keycode(t.upper()) is not None:
            return f"&kp {t.upper()}"
    except Exception:
        pass
    return None
