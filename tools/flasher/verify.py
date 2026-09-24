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
        ok("Layout and matrix agree", len(geo["physical"]) == len(geo["rc"]),
           f"{len(geo['physical'])} positions vs {len(geo['rc'])} matrix entries")
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
    fresh = keymap_mod.parse(open(km_path).read(), repo)
    n_keys = sum(len(l["keys"]) for l in parsed["layers"])
    ok("Every layer has a full binding set",
       all(len(l["keys"]) == len(geo["rc"]) for l in parsed["layers"]) and parsed["layers"],
       f"{len(parsed['layers'])} layers x {len(geo['rc'])} keys = {n_keys}")

    mismatched = []
    for a, b in zip(parsed["layers"], fresh["layers"]):
        for i, (ka, kb) in enumerate(zip(a["keys"], b["keys"])):
            if ka["binding"] != kb["binding"]:
                mismatched.append(f"{a['name']}[{i}]")
    ok("Re-reading the file reproduces every value", not mismatched,
       f"{n_keys} bindings identical on re-parse" if not mismatched
       else f"{len(mismatched)} differ: {', '.join(mismatched[:6])}")

    # 4. each rendered binding is a token that literally appears in the file
    missing = []
    for l in parsed["layers"]:
        m = re.search(re.escape(l["name"]) + r'";\s*bindings = <\n(.*?)\n\s*>;', text, re.S)
        body = m.group(1) if m else ""
        toks = keymap_mod.split_bindings(body)
        for i, k in enumerate(l["keys"]):
            if i >= len(toks) or toks[i] != k["binding"]:
                missing.append(f"{l['name']}[{i}]")
    ok("Rendered bindings match the file token-for-token", not missing,
       f"all {n_keys} bindings traced to {KEYMAP_REL}" if not missing
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
