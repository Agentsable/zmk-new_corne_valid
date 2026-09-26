#!/usr/bin/env python3
"""Deploy controller for the Eyelash Corne.

One update request drives both halves in sequence. Each half walks
blank -> red (waiting) -> orange (bootloader mounted) -> green (flashed);
when both are green the commit can be pushed.

Flashing shells out to adafruit-nrfutil: the Nordic legacy DFU protocol is not
worth reimplementing just to reach it from a browser.
"""
import hashlib, json, os, re, subprocess, threading, time

import keymap as keymap_mod
import verify as verify_mod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "web", "dist")
REPO = os.path.abspath(os.path.join(ROOT, "..", ".."))
PORT = int(os.environ.get("FLASHER_PORT", "8787"))
NRFUTIL = os.environ.get("NRFUTIL", "")
PKG_DIR = os.environ.get("PKG_DIR", "")

PKG = {"left": "left_nice.zip", "right": "right_nice.zip"}
HEX = {"left": "build/left_nice/zephyr/zmk.hex", "right": "build/right_nice/zephyr/zmk.hex"}
WAIT_TIMEOUT = 900  # seconds to wait for a double-tap, per half
VERSION_FMT = "%d-%m-%y_%H-%M"      # e.g. 24-09-26_18-48
DOCKER_IMAGE = "zmkfirmware/zmk-build-arm:stable"
# Local builds must pass the display overlay explicitly: the eyelash_corne west
# module ships a duplicate shield that shadows this repo's copy, so the
# #include in our overlay never reaches dtc here. CI has no such shadow.
OVERLAY = "/workspace/boards/shields/eyelash_corne/oled.dtsi"
SHIELDS = {"left": "eyelash_corne_left nice_oled", "right": "eyelash_corne_right nice_oled"}

LOCK = threading.Lock()
STATE = {"phase": "idle", "left": "blank", "right": "blank", "log": [], "error": "",
         "push": None, "push_msg": "", "version": None, "steps": []}

# workflow steps, in order; the UI renders these with their status
STEPS = [("predeploy", "Commit + push predeploy version"),
         ("build", "Build both halves"),
         ("right", "Flash right half"),
         ("left", "Flash left half"),
         ("deployed", "Commit + push deployed version")]


def step(key, status, detail=""):
    with LOCK:
        steps = [dict(s) for s in STATE["steps"]]
        for s in steps:
            if s["key"] == key:
                s["status"] = status
                if detail:
                    s["detail"] = detail
        STATE["steps"] = steps


def git(*args, timeout=180):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                       text=True, timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def remote_has_tag(tag):
    """A push that exits 0 is not proof the tag landed -- ask the remote."""
    ok, out = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", timeout=60)
    return ok and tag in out


def build_halves():
    """Run the same Docker build that produces the flashed firmware."""
    script = ["set -e", "west zephyr-export >/dev/null 2>&1"]
    for side, shield in SHIELDS.items():
        # Only the left half is the Studio central; the snippet adds an unused
        # USB CDC/console to the peripheral and made local right-half firmware
        # 6.6 KB larger than CI's for no reason.
        snippet = "-S studio-rpc-usb-uart " if side == "left" else ""
        script.append(
            f'west build -s zmk/app -b nice_nano_v2 -d build/{side}_nice '
            f'{snippet}--pristine=never -- '
            f'-DSHIELD="{shield}" -DZMK_CONFIG=/workspace/config '
            f'-DEXTRA_DTC_OVERLAY_FILE={OVERLAY}')
        script.append(f'echo BUILT {side}')
    cmd = ["docker", "run", "--rm", "-v", f"{REPO}:/workspace", "-w", "/workspace",
           DOCKER_IMAGE, "bash", "-c", "\n".join(script)]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            line = line.rstrip()
            if re.search(r"BUILT |error|Error|FLASH:|Wrote ", line):
                log(line)
        if p.wait(timeout=1800) != 0:
            return False
    except Exception as e:
        log(f"build failed: {e}")
        return False
    # repackage for DFU straight from the fresh hex
    for side in SHIELDS:
        hexf = os.path.join(REPO, HEX[side])
        pkg = os.path.join(PKG_DIR, PKG[side])
        r = subprocess.run([NRFUTIL, "dfu", "genpkg", "--dev-type", "0x0052",
                            "--application", hexf, pkg],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log(f"genpkg {side} failed: {r.stderr.strip()}")
            return False
        log(f"packaged {side}")
    return True


def ports():
    try:
        return sorted(p for p in os.listdir("/dev") if p.startswith("cu.usbmodem"))
    except OSError:
        return []


def volume():
    """The Adafruit bootloader mounts NICENANO. This is the reliable DFU tell --
    macOS often hands the bootloader the same port name the firmware had, which
    makes a port-diff alone come up empty."""
    try:
        return next((v for v in os.listdir("/Volumes") if "NICENANO" in v.upper()), None)
    except OSError:
        return None


def bootloader_port(baseline):
    """Port to flash, or None if the board is not in DFU.

    The NICENANO volume is REQUIRED, not a fallback. A port appearing only means
    something was plugged in -- flashing a board that is still running its
    firmware fails mid-write with 'Device not configured'. Only the mounted
    volume proves the Adafruit bootloader is actually running."""
    if not volume():
        return None
    now = ports()
    fresh = [p for p in now if p not in baseline]
    if fresh:
        return fresh[0]
    if len(now) == 1:
        return now[0]
    return None


KEYMAP = os.path.join(REPO, "config", "eyelash_corne.keymap")
STATE_FILE = os.path.join(ROOT, "state.json")


def keymap_sha():
    try:
        return hashlib.sha256(open(KEYMAP, "rb").read()).hexdigest()[:12]
    except OSError:
        return ""


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def save_state(d):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, STATE_FILE)


def repo_url():
    """Blob URL base for the keymap, derived from origin."""
    try:
        u = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO,
                           capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""
    u = re.sub(r"\.git$", "", u)
    u = re.sub(r"^git@github\.com:", "https://github.com/", u)
    return f"{u}/blob/main/config/eyelash_corne.keymap"


def head_subject():
    try:
        return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=REPO,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def request_info():
    """The open update request, if any, plus the last one that was deployed.

    A request is open when the keymap on disk differs from what was deployed --
    that is the only honest definition, since the board runs what was flashed."""
    st = load_state()
    sha = keymap_sha()
    last = st.get("last_deploy")
    pending = st.get("pending")
    is_open = bool(sha) and (not last or last.get("sha") != sha)
    if is_open and (not pending or pending.get("sha") != sha):
        # edited outside this app (an editor, a git checkout)
        at = os.path.getmtime(KEYMAP) if os.path.exists(KEYMAP) else 0
        pending = {"description": head_subject() or "keymap update",
                   "at": at, "sha": sha}
    return {"open": is_open,
            "at": (pending or {}).get("at", 0),
            "description": (pending or {}).get("description", ""),
            "last": last}


def log(msg):
    with LOCK:
        STATE["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del STATE["log"][:-200]


def setk(**kw):
    with LOCK:
        STATE.update(kw)


def flash(side, port):
    pkg = os.path.join(PKG_DIR, PKG[side])
    if not (NRFUTIL and os.path.exists(NRFUTIL) and os.path.exists(pkg)):
        log(f"missing nrfutil or package for {side}")
        return False
    cmd = [NRFUTIL, "dfu", "serial", "--package", pkg, "-p", f"/dev/{port}",
           "-b", "115200", "--singlebank"]
    log(f"flashing {side} on /dev/{port}")
    programmed = False
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, cwd=REPO)
        for line in p.stdout:
            line = line.rstrip()
            # the progress bar is thousands of '#' -- keep the meaningful lines
            if line and not set(line) <= {"#"}:
                log(line)
            if "Device programmed" in line:
                programmed = True
        rc = p.wait(timeout=240)
    except Exception as e:
        log(f"{side} failed: {e}")
        return False
    # adafruit-nrfutil exits 0 even when the transfer dies, so the exit code
    # alone is not evidence -- require its success line.
    if rc != 0 or not programmed:
        log(f"{side}: FAILED (exit {rc}, programmed={programmed})")
        return False
    return True


def wait_for(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.6)
    return None


def flash_half(side):
    """Wait for DFU on one half and flash it. True when programmed."""
    if wait_for(lambda: volume() is None, 60) is None:
        log("previous bootloader volume never unmounted")
    baseline = ports()
    setk(**{side: "red"}, phase=f"{side}_wait")
    log(f"{side}: waiting for bootloader -- double-tap reset (baseline {baseline})")
    port = wait_for(lambda: bootloader_port(baseline), WAIT_TIMEOUT)
    if not port:
        log(f"{side}: timed out waiting for the bootloader")
        setk(**{side: "red"})
        return False
    setk(**{side: "orange"}, phase=f"{side}_flash")
    log(f"{side}: bootloader on /dev/{port}")
    if not flash(side, port):
        setk(**{side: "orange"})
        return False
    setk(**{side: "green"})
    log(f"{side}: programmed")
    return True


def workflow(name):
    """Named release: predeploy commit+push -> build -> flash right, left -> deployed.

    The predeploy tag lands before anything is flashed, so a half-finished
    deployment is still traceable to the exact source that produced it.
    """
    ts = time.strftime(VERSION_FMT)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "update"
    pre, done_tag = f"predeploy_{ts}_{safe}", f"deployed_{ts}_{safe}"
    setk(version={"name": safe, "ts": ts, "predeploy": pre, "deployed": done_tag},
         steps=[{"key": k, "label": l, "status": "todo", "detail": ""} for k, l in STEPS])

    def fail(key, msg):
        step(key, "fail", msg)
        setk(phase="error", error=msg)
        log(f"workflow aborted: {msg}")

    # 1. predeploy commit + push
    step("predeploy", "run")
    setk(phase="predeploy")
    git("add", "config/eyelash_corne.keymap")
    okc, out = git("commit", "-m", pre)
    # A clean tree is normal: a version may tag an unchanged keymap. git words
    # this two different ways depending on whether anything was staged.
    clean = any(m in out for m in ("nothing to commit",
                                   "no changes added to commit",
                                   "nothing added to commit"))
    if not okc and not clean:
        return fail("predeploy", f"commit failed: {out.splitlines()[-1] if out else ''}")
    if clean:
        log("predeploy: keymap unchanged, tagging current commit")
    # Annotated, not lightweight: --follow-tags ignores lightweight tags, which
    # silently left every version tag local-only.
    okt, out = git("tag", "-f", "-a", pre, "-m", f"Predeploy {ts} {safe}")
    if not okt:
        return fail("predeploy", f"tag failed: {out}")
    okp, out = git("push", "origin", "main")
    if not okp:
        return fail("predeploy", f"push failed: {out.splitlines()[-1] if out else ''}")
    okp, out = git("push", "-f", "origin", f"refs/tags/{pre}")
    if not okp:
        return fail("predeploy", f"tag push failed: {out.splitlines()[-1] if out else ''}")
    if not remote_has_tag(pre):
        return fail("predeploy", f"{pre} is not on the remote after pushing")
    step("predeploy", "ok", pre)
    log(f"predeploy pushed and verified on remote: {pre}")

    # 2. build immediately after the predeploy push
    step("build", "run")
    setk(phase="build")
    if not build_halves():
        return fail("build", "firmware build failed")
    step("build", "ok", "both halves built and packaged")

    # 3. flash right, then left
    for side in ("right", "left"):
        step(side, "run")
        if not flash_half(side):
            return fail(side, f"{side} half did not flash")
        step(side, "ok", "programmed")

    # 4. deployed commit + push
    step("deployed", "run")
    setk(phase="deployed")
    git("tag", "-f", "-a", done_tag, "-m", f"Deployed {ts} {safe}")
    git("push", "origin", "main")
    okp, out = git("push", "-f", "origin", f"refs/tags/{done_tag}")
    if not okp or not remote_has_tag(done_tag):
        return fail("deployed", f"tag push failed: {out.splitlines()[-1] if out else ''}")
    step("deployed", "ok", done_tag)
    log(f"deployed pushed and verified on remote: {done_tag}")

    setk(phase="done")
    st = load_state()
    st["last_deploy"] = {"at": time.time(), "sha": keymap_sha(),
                         "description": request_info()["description"] or safe,
                         "version": done_tag}
    st.pop("pending", None)
    save_state(st)
    log(f"deployed: {done_tag}")


def sequence():
    """Both halves, in order: right first, then left."""
    for side in ("right", "left"):   # right first, then left
        # the previous half's bootloader must be gone before arming the next
        if wait_for(lambda: volume() is None, 60) is None:
            log("previous bootloader volume never unmounted")
        baseline = ports()
        setk(**{side: "red"}, phase=f"{side}_wait")
        log(f"{side}: waiting for bootloader -- double-tap reset (baseline {baseline})")
        port = wait_for(lambda: bootloader_port(baseline), WAIT_TIMEOUT)
        if not port:
            log(f"{side}: timed out waiting for the bootloader")
            setk(**{side: "red"}, phase="error", error=f"{side} half never entered DFU")
            return
        setk(**{side: "orange"}, phase=f"{side}_flash")
        log(f"{side}: bootloader on /dev/{port}")
        if not flash(side, port):
            setk(**{side: "orange"}, phase="error", error=f"{side} half failed to flash")
            return
        setk(**{side: "green"})
        log(f"{side}: programmed")
    setk(phase="done")
    req = request_info()
    st = load_state()
    st["last_deploy"] = {"at": time.time(), "sha": keymap_sha(),
                         "description": req["description"] or head_subject()}
    st.pop("pending", None)
    save_state(st)
    log("both halves programmed")


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass  # GETs are pure polling; noise, not signal

    def _audit(self, path, extra=""):
        """Record every mutating request. A file changed under us once with no
        trace of who did it; unexplained writes should be attributable."""
        peer = self.client_address[0] if self.client_address else "?"
        ua = (self.headers.get("User-Agent") or "")[:60]
        log(f"POST {path} from {peer} [{ua}] {extra}")

    def do_GET(self):
        if self.path.startswith("/api/verify"):
            try:
                return self._send(200, verify_mod.run(REPO))
            except Exception as e:
                return self._send(500, {"error": str(e)})
        if self.path.startswith("/api/keymap"):
            src = "current" if "current" in self.path else "pending"
            f = os.path.join(REPO, "config", "eyelash_corne.keymap")
            try:
                if src == "current":
                    # what the board is running == what was committed when flashed
                    text = subprocess.run(
                        ["git", "show", "HEAD:config/eyelash_corne.keymap"], cwd=REPO,
                        capture_output=True, text=True, timeout=10).stdout
                else:
                    text = open(f).read()
                data = keymap_mod.parse(text, REPO)
            except Exception as e:
                return self._send(500, {"error": str(e)})
            data["source"] = src
            data["repo"] = repo_url()
            return self._send(200, data)
        if self.path.startswith("/api/state"):
            with LOCK:
                s = dict(STATE)
            s["request"] = request_info()
            s["ports"] = ports()
            s["volume"] = volume()
            return self._send(200, s)
        rel = self.path.split("?")[0].lstrip("/") or "index.html"
        path = os.path.join(DIST, rel)
        if not os.path.isfile(path):
            path = os.path.join(DIST, "index.html")
        if not os.path.isfile(path):
            return self._send(503, b"run: npm run build", "text/plain")
        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml"}.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        self._audit(self.path.split("?")[0])
        if self.path.startswith("/api/start"):
            with LOCK:
                if STATE["phase"] not in ("idle", "error", "done"):
                    return self._send(409, {"error": "already running"})
                STATE.update(phase="starting", left="blank", right="blank",
                             log=[], error="", push=None, push_msg="")
            name = ""
            try:
                name = (json.loads(raw or b"{}") or {}).get("name", "")
            except Exception:
                pass
            target = (lambda: workflow(name)) if name else sequence
            threading.Thread(target=target, daemon=True).start()
            return self._send(200, {"ok": True, "named": bool(name)})
        if self.path.startswith("/api/keymap"):
            try:
                body = json.loads(self.rfile.read(n) if False else b"{}")
            except Exception:
                body = {}
            return self._send(400, {"error": "use PUT semantics via /api/save"})
        if self.path.startswith("/api/save"):
            try:
                body = json.loads(raw or b"{}")
                edits = body.get("edits") or []
                if not edits:
                    return self._send(400, {"error": "no edits"})
                text = keymap_mod.set_bindings(open(KEYMAP).read(), edits)
                open(KEYMAP, "w").write(text)
            except Exception as e:
                return self._send(400, {"error": str(e)})
            st = load_state()
            st["pending"] = {
                "description": (body.get("description") or "").strip()
                               or f"Edited {len(edits)} key(s) via the flasher",
                "at": time.time(), "sha": keymap_sha()}
            save_state(st)
            log(f"keymap saved: {len(edits)} edit(s) -> " +
                ", ".join(f"{e.get('layer')}[{e.get('index')}]={e.get('binding')}"
                          for e in edits[:6]))
            return self._send(200, {"ok": True, "sha": st["pending"]["sha"]})
        if self.path.startswith("/api/push"):
            with LOCK:
                if STATE["phase"] != "done":
                    return self._send(409, {"error": "not finished"})
            try:
                r = subprocess.run(["git", "push", "origin", "main"], cwd=REPO,
                                   capture_output=True, text=True, timeout=120)
                out = (r.stdout + r.stderr).strip().splitlines()
                msg = out[-1] if out else "pushed"
                ok = r.returncode == 0
            except Exception as e:
                ok, msg = False, str(e)
            setk(push="ok" if ok else "error", push_msg=msg)
            log(f"git push: {msg}")
            return self._send(200, {"ok": ok, "message": msg})
        self._send(404, {"error": "no route"})


if __name__ == "__main__":
    print(f"deploy controller on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
