"""Checks that what the app renders comes from the local firmware sources.

Every check re-reads the files independently of whatever the UI last fetched,
so a stale cache or a hand-edited table shows up as a failure rather than
quietly passing.
"""
import hashlib, os, re, subprocess

import keymap as keymap_mod
import layout as layout_mod

KEYMAP_REL = "config/eyelash_corne.keymap"


def _sha(b):
    return hashlib.sha256(b).hexdigest()[:12]


def run(repo):
    checks = []

    def ok(name, passed, detail):
        checks.append({"name": name, "ok": bool(passed), "detail": detail})

    km_path = os.path.join(repo, KEYMAP_REL)
    raw = open(km_path, "rb").read()
    text = raw.decode()

    # 1. geometry comes from the shield sources, not a table in this app
    try:
        geo = layout_mod.analyse(repo)
        ok("Physical layout parsed from shield source", len(geo["physical"]) > 0,
           f"{len(geo['physical'])} keys from {layout_mod.LAYOUTS}")
        ok("Matrix transform parsed from shield source", len(geo["rc"]) > 0,
           f"{len(geo['rc'])} RC entries from {layout_mod.SHIELD}")
        # analyse() raises when these disagree, so this can only ever be seen
        # passing. Re-parse both sides independently so the check has something
        # real to compare and a degraded parse shows up as a failure here.
        raw_phys = layout_mod.physical(repo)
        raw_rc = layout_mod.transform(repo)
        ok("Layout and matrix agree",
           len(raw_phys) == len(raw_rc) == len(geo["physical"]) > 0,
           f"{len(raw_phys)} positions vs {len(raw_rc)} matrix entries")
    except Exception as e:
        ok("Geometry parsed from shield source", False, str(e))
        return {"checks": checks, "passed": 0, "total": len(checks)}

    # 2. joystick + rotary detected, never indexed by hand
    cols = {geo["rc"][i][1] for i in geo["joystick"]}
    ok("Joystick detected by shape, not hardcoded", len(geo["joystick"]) == 5 and len(cols) == 1,
       f"{len(geo['joystick'])} keys on matrix column {cols.pop() if len(cols)==1 else cols}: "
       + ", ".join(f"{i}={d}" for i, d in sorted(geo["joystick"].items())))
    ok("Rotary push tied to a declared encoder", geo["rotary"] is not None
       and layout_mod.has_left_encoder(repo),
       f"index {geo['rotary']} at RC{geo['rc'][geo['rotary']]}" if geo["rotary"] is not None
       else "no encoder declared")

    # 3. the render is built from this exact file
    parsed = keymap_mod.parse(text, repo)
    with open(km_path) as fh:
        fresh = keymap_mod.parse(fh.read(), repo)
    n_keys = sum(len(l["keys"]) for l in parsed["layers"])
    # Zero layers used to sail through the three checks below: an empty list
    # compared to an empty list, reported as "0 bindings identical on re-parse".
    # Nothing downstream may claim to have verified what it never saw.
    if not parsed["layers"]:
        ok("Keymap parsed into layers", False,
           "no layers parsed -- every binding check below would pass vacuously")
        return {"checks": checks, "passed": sum(1 for c in checks if c["ok"]),
                "total": len(checks)}
    ok("Keymap parsed into layers", True,
       f"{len(parsed['layers'])} layers, {n_keys} bindings")
    ok("Every layer has a full binding set",
       all(len(l["keys"]) == len(geo["rc"]) for l in parsed["layers"]) and parsed["layers"],
       f"{len(parsed['layers'])} layers x {len(geo['rc'])} keys = {n_keys}")

    mismatched = []
    for a, b in zip(parsed["layers"], fresh["layers"]):
        for i, (ka, kb) in enumerate(zip(a["keys"], b["keys"])):
            if ka["binding"] != kb["binding"]:
                mismatched.append(f"{a['name']}[{i}]")
    # compared is what was actually examined; "not mismatched" alone is true of
    # an empty comparison as well as an agreeing one.
    compared = sum(len(a["keys"]) for a, b in zip(parsed["layers"], fresh["layers"]))
    ok("Re-reading the file reproduces every value",
       not mismatched and compared == n_keys and n_keys > 0,
       f"{compared} bindings identical on re-parse" if not mismatched
       else f"{len(mismatched)} differ: {', '.join(mismatched[:6])}")

    # 4. each rendered binding is a token that literally appears in the file
    missing, traced = [], 0
    for l in parsed["layers"]:
        m = re.search(re.escape(l["name"]) + r'";\s*bindings = <\n(.*?)\n\s*>;', text, re.S)
        body = m.group(1) if m else ""
        toks = keymap_mod.split_bindings(body)
        for i, k in enumerate(l["keys"]):
            if i >= len(toks) or toks[i] != k["binding"]:
                missing.append(f"{l['name']}[{i}]")
            else:
                traced += 1
    ok("Rendered bindings match the file token-for-token",
       not missing and traced == n_keys and n_keys > 0,
       f"all {traced} bindings traced to {KEYMAP_REL}" if not missing
       else f"{len(missing)} untraceable: {', '.join(missing[:6])}")

    # 5. local working tree vs the committed keymap the 'current' page shows
    try:
        head = subprocess.run(["git", "show", f"HEAD:{KEYMAP_REL}"], cwd=repo,
                              capture_output=True, timeout=10).stdout
    except Exception:
        head = b""
    same = head == raw
    ok("Local file matches the committed version", same,
       f"sha {_sha(raw)}" + ("" if same else f" vs HEAD {_sha(head)} - uncommitted edits present"))

    passed = sum(c["ok"] for c in checks)
    return {"checks": checks, "passed": passed, "total": len(checks),
            "sha": _sha(raw), "path": KEYMAP_REL}
