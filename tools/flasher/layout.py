"""Derive the board's physical layout and matrix map from the shield sources.

Nothing here is hand-copied: positions come from eyelash_corne-layouts.dtsi and
the row/column of every key comes from the matrix transform in
eyelash_corne.dtsi. If the firmware changes, this changes with it.
"""
import os, re

LAYOUTS = "boards/shields/eyelash_corne/eyelash_corne-layouts.dtsi"
SHIELD = "boards/shields/eyelash_corne/eyelash_corne.dtsi"
RIGHT_OVERLAY = "boards/shields/eyelash_corne/eyelash_corne_right.overlay"

KEY_RE = re.compile(
    r"key_physical_attrs\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\(?-?\d+\)?)\s+(\d+)\s+(\d+)")
RC_RE = re.compile(r"RC\((\d+),(\d+)\)")


def _n(tok):
    return int(tok.strip("()"))


def read(repo, rel):
    with open(os.path.join(repo, rel)) as f:
        return f.read()


def physical(repo):
    """[(x, y, w, h, rot, rx, ry)] in declaration order."""
    text = read(repo, LAYOUTS)
    keys = []
    for m in KEY_RE.finditer(text):
        w, h, x, y, r, rx, ry = (_n(g) for g in m.groups())
        keys.append((x, y, w, h, r, rx, ry))
    return keys


def transform(repo):
    """[(row, col)] in keymap-binding order, straight from the transform map."""
    text = read(repo, SHIELD)
    m = re.search(r"default_transform:.*?map = <(.*?)>;", text, re.S)
    if not m:
        raise ValueError("matrix transform not found")
    return [(int(r), int(c)) for r, c in RC_RE.findall(m.group(1))]


def col_offset(repo):
    """Columns >= this belong to the right half."""
    try:
        text = read(repo, RIGHT_OVERLAY)
    except OSError:
        return None
    m = re.search(r"col-offset\s*=\s*<(\d+)>", text)
    return int(m.group(1)) if m else None


def has_left_encoder(repo):
    """True when the shield enables the left-hand encoder."""
    try:
        text = read(repo, "boards/shields/eyelash_corne/eyelash_corne_left.overlay")
    except OSError:
        return False
    return bool(re.search(r"&left_encoder\s*\{[^}]*status\s*=\s*\"okay\"", text, re.S))


def analyse(repo):
    """Physical + matrix data joined, with the joystick found by construction.

    The 5-way joystick is the matrix column carrying five keys that form a plus
    around a shared centre. Detected, never assumed: if the wiring changes the
    detection follows it.
    """
    phys, rc = physical(repo), transform(repo)
    if len(phys) != len(rc):
        raise ValueError(f"layout has {len(phys)} keys, transform has {len(rc)}")

    by_col = {}
    for i, (r, c) in enumerate(rc):
        by_col.setdefault(c, []).append(i)

    joystick, rotary = {}, None
    for col, idxs in by_col.items():
        if len(idxs) != 5:
            continue
        pts = {i: (phys[i][0], phys[i][1]) for i in idxs}
        xs = sorted({p[0] for p in pts.values()})
        ys = sorted({p[1] for p in pts.values()})
        if len(xs) != 3 or len(ys) != 3:
            continue          # not a plus
        cx, cy = xs[1], ys[1]
        cand = {}
        for i, (x, y) in pts.items():
            if x == cx and y == ys[0]: cand[i] = "up"
            elif x == cx and y == ys[2]: cand[i] = "down"
            elif y == cy and x == xs[0]: cand[i] = "left"
            elif y == cy and x == xs[2]: cand[i] = "right"
            elif x == cx and y == cy: cand[i] = "centre"
        if len(cand) == 5 and set(cand.values()) == {"up","down","left","right","centre"}:
            joystick = cand
            break

    # The rotary push is the left-half key that stands apart from every other
    # left-half key -- the encoder sits in the gap between the halves. Measured,
    # not indexed, so it survives a layout change.
    off = col_offset(repo)
    if off:
        left = [i for i, (r, c) in enumerate(rc) if c < off]
        # ponytail: the encoder push is the innermost left-half key -- it sits in
        # the gap between the halves, past every other left key. Holds while the
        # shield declares one encoder on the left; a second would need the sensor
        # node's own position, which the devicetree does not carry.
        if left and has_left_encoder(repo):
            rotary = max(left, key=lambda i: phys[i][0])
    return {"physical": phys, "rc": rc, "joystick": joystick, "rotary": rotary,
            "col_offset": off}
