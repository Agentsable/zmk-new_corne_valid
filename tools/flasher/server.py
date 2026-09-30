#!/usr/bin/env python3
"""Deploy controller for the Eyelash Corne.

One update request drives both halves in sequence. Each half walks
blank -> red (waiting) -> orange (bootloader mounted) -> green (flashed);
when both are green the commit can be pushed.

Flashing shells out to adafruit-nrfutil: the Nordic legacy DFU protocol is not
worth reimplementing just to reach it from a browser.
"""
import base64, hashlib, hmac, json, os, re, subprocess, threading, time

import keymap as keymap_mod
import verify as verify_mod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "web", "dist")
REPO = os.path.abspath(os.path.join(ROOT, "..", ".."))


def current_build():
    """Identity of the UI being served: Vite's content hash in the bundle name.

    ponytail: the filename is already a content hash, so there is nothing to
    compute or store. Empty when dist is missing, which disables the check.
    """
    try:
        return next(f for f in sorted(os.listdir(os.path.join(DIST, "assets")))
                    if f.endswith(".js"))
    except (OSError, StopIteration):
        return ""
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
# /api/save is read-modify-write on one file under a threading HTTP server. Two
# clients saving at once lost one set of edits and recorded a description that
# belonged to the other -- the same "named after changes it does not contain"
# failure this tool already had once.
SAVE_LOCK = threading.Lock()
STATE = {"phase": "idle", "left": "blank", "right": "blank", "log": [], "error": "",
         "version": None, "steps": []}

# workflow steps, in order; the UI renders these with their status
STEPS = [("build", "Build both halves"),
         ("predeploy", "Commit + push predeploy version"),
         ("right", "Flash right half"),
         ("left", "Flash left half"),
         ("deployed", "Commit + push deployed version")]


def run_streaming(cmd, timeout, keep, cwd=None):
    """Run cmd, log the lines matching `keep`, and return its exit code or None.

    Iterating p.stdout blocks with no timeout of its own, so the p.wait(timeout=)
    that used to follow it was unreachable: a Docker build that stalled or an
    nrfutil blocked on a serial read from an unplugged board hung the workflow
    thread forever, with the UI showing a live-looking log that never advanced.
    A watchdog that kills the child is what makes the read loop end.
    """
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, cwd=cwd)
    timed_out = []

    def kill():
        timed_out.append(True)
        for shot in (p.terminate, p.kill):
            try:
                shot()
            except Exception:
                pass
            if p.poll() is not None:
                return
            time.sleep(2)

    watchdog = threading.Timer(timeout, kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        for line in p.stdout:
            keep(line.rstrip())
        rc = p.wait()
    finally:
        watchdog.cancel()
    if timed_out:
        log(f"timed out after {timeout}s and was killed: {cmd[0]}")
        return None
    return rc


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
        # build.yaml passes these in CI, and this build passed nothing, so every
        # locally flashed board came out with Studio locking ON while the repo
        # said it was off. Locking is also self-defeating here: it re-locks on
        # every disconnect, and the unlock behaviour sits behind a layer only
        # the peripheral can reach.
        studio = ("-DCONFIG_ZMK_STUDIO=y -DCONFIG_ZMK_STUDIO_LOCKING=n "
                  if side == "left" else "")
        script.append(
            f'west build -s zmk/app -b nice_nano_v2 -d build/{side}_nice '
            f'{snippet}--pristine=never -- '
            f'-DSHIELD="{shield}" -DZMK_CONFIG=/workspace/config '
            f'{studio}'
            f'-DEXTRA_DTC_OVERLAY_FILE={OVERLAY}')
        script.append(f'echo BUILT {side}')
    cmd = ["docker", "run", "--rm", "-v", f"{REPO}:/workspace", "-w", "/workspace",
           DOCKER_IMAGE, "bash", "-c", "\n".join(script)]
    def keep(line):
        if re.search(r"BUILT |error|Error|FLASH:|Wrote ", line):
            log(line)
    try:
        if run_streaming(cmd, 1800, keep) != 0:
            return False
    except Exception as e:
        log(f"build failed: {e}")
        return False
    # genpkg sat outside the try, and unlike flash() nothing here checked that
    # NRFUTIL is set -- so `./deploy.py name`, which runs on the system
    # interpreter where run.sh has exported nothing, crashed here AFTER the
    # predeploy tag was already pushed.
    if not (NRFUTIL and os.path.exists(NRFUTIL)):
        log("no adafruit-nrfutil: set NRFUTIL or start the flasher with ./run.sh")
        return False
    if not PKG_DIR:
        log("no PKG_DIR: set it or start the flasher with ./run.sh")
        return False
    os.makedirs(PKG_DIR, exist_ok=True)
    # repackage for DFU straight from the fresh hex
    for side in SHIELDS:
        hexf = os.path.join(REPO, HEX[side])
        pkg = os.path.join(PKG_DIR, PKG[side])
        try:
            r = subprocess.run([NRFUTIL, "dfu", "genpkg", "--dev-type", "0x0052",
                                "--application", hexf, pkg],
                               capture_output=True, text=True, timeout=120)
        except Exception as e:
            log(f"genpkg {side} failed: {e}")
            return False
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
# Shared secret for requests that arrive through the Cloudflare tunnel. Written
# by the hosted-app setup; absent on a machine that never hosts, where remote
# requests are refused outright rather than allowed through unchecked.
REMOTE_SECRET_FILE = os.path.join(ROOT, ".remote-secret")


def remote_secret():
    try:
        return open(REMOTE_SECRET_FILE).read().strip()
    except OSError:
        return ""


HOSTED_SECRETS_FILE = os.path.join(ROOT, ".hosted-secrets.json")


def basic_credentials():
    """(user, password) for browsers reaching this server over the tunnel.

    The same pair the hosted Worker uses, so there is one login to remember
    rather than two. Absent on a machine that never hosts, where browser access
    over the tunnel is simply refused.
    """
    try:
        d = json.load(open(HOSTED_SECRETS_FILE))
        return d.get("basic_user", ""), d.get("basic_pass", "")
    except Exception:
        return "", ""
STATE_FILE = os.path.join(ROOT, "state.json")
AUDIT_LOG = os.path.join(ROOT, "audit.log")


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
    """Subject of the last commit that touched the keymap.

    Not HEAD. A pending request describes a keymap change, and any number of
    commits to the flasher or the docs can land on top of it -- reporting HEAD
    then labels the request with something that changed no keys at all.
    """
    for args in (["log", "-1", "--format=%s", "--", KEYMAP], ["log", "-1", "--format=%s"]):
        try:
            out = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
        if out:
            return out
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
            "sha": sha,
            "last": last}


def log(msg):
    with LOCK:
        STATE["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del STATE["log"][:-200]
    # STATE["log"] is capped at 200 and dies with the process, so _audit's record
    # of every mutating request and the "refused remote request" security line
    # vanish exactly when they would be wanted. Append somewhere that survives.
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except OSError:
        pass        # a broken audit file must never take down a request


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
    def keep(line):
        nonlocal programmed
        # the progress bar is thousands of '#' -- keep the meaningful lines
        if line and not set(line) <= {"#"}:
            log(line)
        if "Device programmed" in line:
            programmed = True
    try:
        rc = run_streaming(cmd, 240, keep, cwd=REPO)
    except Exception as e:
        log(f"{side} failed: {e}")
        return False
    if rc is None:
        log(f"{side}: FAILED (nrfutil stopped responding and was killed)")
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
    # The volume mounts before the CDC endpoint is ready to be written, so the
    # first write can die with "Device not configured" on a board that is
    # perfectly fine. Settle, then retry while the bootloader is still there --
    # re-resolving the port each time, because macOS can rename it.
    programmed = False
    for attempt in range(3):
        if attempt:
            time.sleep(2.0)
            # baseline, not [] -- with an empty baseline every cu.usbmodem* is
            # "fresh" and sorted()[0] wins, which can point nrfutil at a board
            # that is running its firmware and kill it mid-write.
            again = bootloader_port(baseline)
            if not again:
                log(f"{side}: bootloader went away before the retry")
                break
            port = again
            log(f"{side}: retry {attempt} on /dev/{port}")
        if flash(side, port):
            programmed = True
            break
    if not programmed:
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

    # 1. build FIRST. This used to run after the predeploy push, so a build
    # failure left origin/main advertising a keymap no board runs -- and
    # /api/keymap?current reads HEAD, so "Current keymap" showed keys that were
    # never flashed. Nothing reaches the remote now unless it compiled.
    step("build", "run")
    setk(phase="build")
    if not build_halves():
        return fail("build", "firmware build failed")
    step("build", "ok", "both halves built and packaged")

    # 2. predeploy commit + push
    step("predeploy", "run")
    setk(phase="predeploy")
    # Docker builds the working tree, not the commit, so anything dirty outside
    # the keymap is in the firmware but not in the tag. Say so rather than let
    # the tag quietly misdescribe what shipped.
    ok_st, dirty = git("status", "--porcelain")
    extra = [l for l in dirty.splitlines()
             if l[3:].strip() and not l[3:].strip().endswith("eyelash_corne.keymap")]
    if ok_st and extra:
        log(f"warning: {len(extra)} uncommitted file(s) are in this build but not "
            f"in the tag: {', '.join(l[3:].strip() for l in extra[:5])}")
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

    # 3. flash right, then left
    for side in ("right", "left"):
        step(side, "run")
        if not flash_half(side):
            return fail(side, f"{side} half did not flash")
        step(side, "ok", "programmed")

    # 4. deployed commit + push
    step("deployed", "run")
    setk(phase="deployed")
    okt, out = git("tag", "-f", "-a", done_tag, "-m", f"Deployed {ts} {safe}")
    if not okt:
        return fail("deployed", f"tag failed: {out.splitlines()[-1] if out else ''}")
    # This push used to be called bare. A failed one is invisible -- the tag push
    # below still ships the objects, so remote_has_tag passes and the page prints
    # "Deployment complete." while origin/main still points at the old keymap.
    okm, out = git("push", "origin", "main")
    if not okm:
        return fail("deployed", f"push failed: {out.splitlines()[-1] if out else ''}")
    okp, out = git("push", "-f", "origin", f"refs/tags/{done_tag}")
    if not okp or not remote_has_tag(done_tag):
        return fail("deployed", f"tag push failed: {out.splitlines()[-1] if out else ''}")
    step("deployed", "ok", done_tag)
    log(f"deployed pushed and verified on remote: {done_tag}")

    st = load_state()
    st["last_deploy"] = {"at": time.time(), "sha": keymap_sha(),
                         "description": request_info()["description"] or safe,
                         "version": done_tag}
    st.pop("pending", None)
    save_state(st)
    # after save_state: "done" used to be set first, so a failed write left the
    # UI saying complete while the request stayed open and notify.js re-fired.
    setk(phase="done")
    log(f"deployed: {done_tag}")


def guarded(fn):
    """Run the workflow so it can never leave the phase mid-flight.

    /api/start refuses anything whose phase is not idle/error/done, and nothing
    used to reset it: one escaping exception (a git timeout, an unguarded
    save_state) wedged the tool at phase="build" until the process restarted,
    with the UI showing a frozen step list and no error.
    """
    def run():
        try:
            fn()
        except Exception as e:
            log(f"update crashed: {e!r}")
            setk(phase="error", error=f"The update stopped unexpectedly: {e}")
        finally:
            with LOCK:
                if STATE["phase"] not in ("done", "error"):
                    STATE["phase"] = "error"
                    STATE["error"] = (STATE["error"]
                                      or "The update stopped without finishing.")
    return run


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

    def _remote_ok(self):
        """Refuse tunnel traffic that does not carry the shared secret.

        Cf-Ray is set by Cloudflare, so it marks exactly the requests that came
        in over the tunnel; a direct call from this Mac never has it and is left
        alone. Checked in one place because every route -- flashing, saving the
        keymap, driving git -- is equally worth protecting.
        """
        if not self.headers.get("Cf-Ray"):
            return True

        # The Worker's way in: a shared secret no browser can be made to send.
        want = remote_secret()
        got = self.headers.get("X-Flasher-Secret", "")
        if want and hmac.compare_digest(want, got):
            return True

        # A person's way in: the same credentials the hosted app uses, so this
        # host is usable directly in a browser rather than only as plumbing.
        user, pw = basic_credentials()
        if user and pw:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    given = base64.b64decode(auth[6:]).decode("utf-8", "replace")
                except Exception:
                    given = ""
                if hmac.compare_digest(f"{user}:{pw}", given):
                    return True

        path = self.path.split("?")[0]
        log(f"refused remote request to {path} (no secret, no valid sign-in)")
        # Challenge only on a navigation. On an API route a browser would answer
        # WWW-Authenticate with a native dialog, and a fetch behind that dialog
        # never settles -- the page would hang rather than report the problem.
        if path.startswith("/api/"):
            self._send(401, {"kind": "auth", "error": "Sign in to reach the flasher."})
        else:
            body = b"Sign in to reach the flasher.\n"
            self.send_response(401)
            self.send_header("WWW-Authenticate",
                             'Basic realm="Eyelash Corne flasher", charset="UTF-8"')
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return False

    def do_GET(self):
        if not self._remote_ok():
            return
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
                    r = subprocess.run(
                        ["git", "show", "HEAD:config/eyelash_corne.keymap"], cwd=REPO,
                        capture_output=True, text=True, timeout=10)
                    # A failed `git show` exits 128 with EMPTY stdout, and parse("")
                    # returns layers=[] with a full layout and rc -- a 200 that the
                    # coordinate card renders confidently with 27 of 48 labels
                    # renumbered. Never let the empty string through as a keymap.
                    if r.returncode != 0 or not r.stdout.strip():
                        return self._send(500, {"error":
                            "Could not read the committed keymap from git: "
                            + ((r.stderr or "").strip() or "no output")})
                    text = r.stdout
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
        if not self._remote_ok():
            return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        self._audit(self.path.split("?")[0])
        if self.path.startswith("/api/start"):
            try:
                body = json.loads(raw or b"{}") or {}
            except Exception:
                body = {}
            # A tab loaded before the last rebuild runs code we have already
            # fixed. That is how 22:38 and 23:07 were lost: a stale page posted
            # straight here, skipping the save, and flashed a keymap without the
            # edits queued in it. Refuse rather than deploy on behalf of code
            # this server is no longer serving.
            # Cf-Ray is added by Cloudflare, so it is present only on requests
            # that arrived through the tunnel and absent on a direct local call.
            # The hosted UI is rebuilt from git on every push, so it cannot be
            # the stale cached tab this guard exists to catch -- a marker is
            # enough there, while local tabs keep the strict hash check.
            supplied = body.get("build", "")
            cur = current_build()
            if supplied and cur and supplied == cur:
                # Served by this server, so the hash is authoritative wherever
                # the request came from -- including a browser on the tunnel
                # hostname, which carries Cf-Ray but is not the hosted UI.
                stale = False
            elif self.headers.get("Cf-Ray"):
                # The hosted UI, rebuilt from git on every push, so it cannot be
                # the stale cached tab this guard exists to catch.
                stale = not supplied.startswith("remote:")
            else:
                stale = bool(cur) and supplied != cur
            if stale:
                return self._send(409, {"error":
                    "This page is out of date - reload it (Cmd-R) and send again."})
            name = body.get("name", "")
            with LOCK:
                if STATE["phase"] not in ("idle", "error", "done"):
                    return self._send(409, {"error": "already running"})
                STATE.update(phase="starting", left="blank", right="blank",
                             log=[], error="")
            # An unnamed update used to run sequence(), which never built: it
            # flashed the packages left in PKG_DIR by an earlier build, then
            # recorded the CURRENT keymap as deployed and closed the request.
            # There is one path now, and it always builds what it flashes.
            threading.Thread(target=guarded(lambda: workflow(name)),
                             daemon=True).start()
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
                with SAVE_LOCK:
                    text = keymap_mod.set_bindings(open(KEYMAP).read(), edits)
                    with open(KEYMAP, "w") as fh:
                        fh.write(text)
                    st = load_state()
                    st["pending"] = {
                        "description": (body.get("description") or "").strip()
                                       or f"Edited {len(edits)} key(s) via the flasher",
                        "at": time.time(), "sha": keymap_sha()}
                    save_state(st)
            except Exception as e:
                return self._send(400, {"error": str(e)})
            log(f"keymap saved: {len(edits)} edit(s) -> " +
                ", ".join(f"{e.get('layer')}[{e.get('index')}]={e.get('binding')}"
                          for e in edits[:6]))
            return self._send(200, {"ok": True, "sha": st["pending"]["sha"]})
        if self.path.startswith("/api/translate"):
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            binding = keymap_mod.to_binding(body.get("text", ""))
            if not binding:
                return self._send(200, {"ok": False, "error": "not a key I recognise"})
            try:
                main, sub = keymap_mod.label(binding, {"fast": 0, "slow": 0})
            except Exception as e:
                return self._send(200, {"ok": False, "error": f"incomplete binding ({e})"})
            if sub == "\u2026":
                return self._send(200, {"ok": False, "error": "needs a parameter"})
            return self._send(200, {"ok": True, "binding": binding,
                                    "main": main, "sub": sub})

        if self.path.startswith("/api/zmk/"):
            # Imported here, not at module scope: deploy.py runs on the system
            # interpreter, which has no protobuf. Flashing must not depend on
            # this page being usable.
            try:
                import zmk_diff, zmk_rpc
            except ImportError as e:
                return self._send(503, {"kind": "no_deps", "error":
                    f"ZMK RPC deps missing ({e}). Recreate .venv via run.sh."})

            if self.path.startswith("/api/zmk/decide"):
                try:
                    body = json.loads(raw or b"{}")
                    key, adopt = body["key"], bool(body["adopt"])
                    layer, idx = int(key.split("/")[0]), int(key.split("/")[1])
                except Exception as e:
                    return self._send(400, {"error": f"bad request: {e}"})
                st = load_state()
                rejected = set(st.get("zmk_rejected", []))
                if adopt:
                    binding = body.get("binding")
                    if not binding:
                        return self._send(400, {"error": "adopt needs the binding text"})
                    src = keymap_mod.parse(open(KEYMAP).read(), REPO)
                    if layer >= len(src["layers"]):
                        return self._send(400, {"error": f"no layer {layer} in source"})
                    name = src["layers"][layer]["name"]
                    try:
                        text = keymap_mod.set_bindings(
                            open(KEYMAP).read(),
                            [{"layer": name, "index": idx, "binding": binding}])
                    except ValueError as e:
                        return self._send(400, {"error": str(e)})
                    open(KEYMAP, "w").write(text)
                    rejected.discard(key)
                    log(f"zmk: adopted {name}[{idx}] = {binding}")
                else:
                    rejected.add(key)
                st["zmk_rejected"] = sorted(rejected)
                save_state(st)
                return self._send(200, {"ok": True, "adopted": adopt})

            if self.path.startswith("/api/zmk/clear"):
                st = load_state()
                st["zmk_rejected"] = []
                save_state(st)
                return self._send(200, {"ok": True})

            # read + diff
            port = (ports() or [None])[0]   # ports() is live; STATE has no "ports" key
            if not port:
                return self._send(409, {"kind": "no_port",
                                        "error": "No keyboard serial port detected."})
            try:
                km, behaviors = zmk_rpc.read_board("/dev/" + port)
            except zmk_rpc.RpcError as e:
                return self._send(409, {"kind": e.kind, "error": str(e)})
            except Exception as e:
                return self._send(500, {"kind": "failed", "error": str(e)})

            board = [{"name": L.name,
                      "bindings": [{"behavior_id": b.behavior_id,
                                    "param1": b.param1, "param2": b.param2}
                                   for b in L.bindings]}
                     for L in km.layers]
            src = keymap_mod.parse(open(KEYMAP).read(), REPO)
            rejected = load_state().get("zmk_rejected", [])
            return self._send(200, {
                "ok": True,
                "layers": zmk_diff.diff(src["layers"], board, behaviors, rejected),
                "layout": src["layout"],
            })
        self._send(404, {"error": "no route"})


if __name__ == "__main__":
    print(f"deploy controller on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
