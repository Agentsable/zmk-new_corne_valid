"""Self-check for bootloader detection and half identity.

Run: python3 test_detect.py
"""
import os, subprocess, sys, tempfile, textwrap
import server

# flash_half() logs, and server.log() appends to the real audit.log -- the
# durable record of what was actually flashed. A self-check writing fake
# "left: refusing" lines in there is indistinguishable from the real thing.
server.AUDIT_LOG = os.path.join(tempfile.gettempdir(), "flasher_selfcheck_audit.log")
# Nothing in here may shell out to a real DFU tool against a real port. This
# used to be os.environ["NRFUTIL"]="", which stopped working once server.py
# started falling back to .venv/bin/adafruit-nrfutil when the env var is unset.
server.NRFUTIL = ""

def main():
    rv, rp = server.volume, server.ports
    try:
        # a plugged-in board with NO volume is NOT in DFU, however fresh the port.
        # This is the bug that made a failed flash report success.
        server.volume = lambda: None; server.ports = lambda: ["cu.usbmodem1301"]
        assert server.bootloader_port([]) is None
        assert server.bootloader_port(["cu.usbmodem9999"]) is None
        # volume mounted + fresh port
        server.volume = lambda: "NICENANO"; server.ports = lambda: ["cu.usbmodem1401"]
        assert server.bootloader_port(["cu.usbmodem1301"]) == "cu.usbmodem1401"
        # volume mounted, bootloader reclaimed the same port name
        server.ports = lambda: ["cu.usbmodem1301"]
        assert server.bootloader_port(["cu.usbmodem1301"]) == "cu.usbmodem1301"
        # volume mounted but two ports and none fresh -> refuse to guess
        server.ports = lambda: ["a", "b"]
        assert server.bootloader_port(["a", "b"]) is None
        # volume mounted, nothing attached
        server.ports = lambda: []
        assert server.bootloader_port([]) is None
        print("detection self-check: 6 passed")
    finally:
        server.volume, server.ports = rv, rp


def half_identity():
    """Both halves are nice_nano_v2 with the same bootloader and the same
    NICENANO volume. The USB serial is the only thing that differs, so this is
    the whole of the protection against flashing the wrong one."""
    real_serial, real_load, real_save = (server.port_serial, server.load_state,
                                         server.save_state)
    store = {}
    try:
        server.load_state = lambda: dict(store)
        server.save_state = lambda d: store.update(d)
        server.port_serial = lambda port: "LEFTSERIAL"

        # nothing learned yet: there is nothing to compare against, so allow
        assert server.check_half("left", "cu.x") is None
        assert server.check_half("right", "cu.x") is None

        server.remember_half("left", "cu.x")
        assert store["half_serials"]["left"] == "LEFTSERIAL"

        # the LEFT half is in DFU and the run wants to flash RIGHT -> refuse
        why = server.check_half("right", "cu.x")
        assert why and "left half" in why, why
        # ... and flashing LEFT is still fine
        assert server.check_half("left", "cu.x") is None

        # an unreadable serial must not block a flash; it only loses the check
        server.port_serial = lambda port: ""
        assert server.check_half("right", "cu.x") is None
        print("half-identity self-check: 5 passed")
    finally:
        server.port_serial, server.load_state, server.save_state = (
            real_serial, real_load, real_save)


def deploy_lock():
    """The lock has to hold across PROCESSES: STATE is per-process, so the
    /api/start gate cannot see ./deploy.py and vice versa."""
    fh = server.acquire_deploy_lock()
    try:
        r = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""
                import os
                os.environ.setdefault("NRFUTIL", ""); os.environ.setdefault("PKG_DIR", "")
                import server
                try:
                    server.acquire_deploy_lock()
                    raise SystemExit("held lock twice")
                except server.DeployBusy:
                    pass
            """)],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)))
        assert r.returncode == 0, f"second process was not refused: {r.stdout}{r.stderr}"
    finally:
        server.release_deploy_lock(fh)
    # and the lock is genuinely released
    fh2 = server.acquire_deploy_lock()
    server.release_deploy_lock(fh2)
    print("deploy-lock self-check: 2 passed")


def retry_rewait():
    """flash_half used to give up when a failed write left the board out of DFU,
    stranding one half on old firmware. It now waits for another double-tap --
    and that second wait must police half identity too, or the retry path
    becomes the one way to flash the wrong half and call it success."""
    real = (server.volume, server.ports, server.port_serial, server.load_state,
            server.flash, server.wait_for, server.remember_half)
    try:
        # volume mounted but no fresh port, so bootloader_port() inside the
        # retry loop returns None -- the "bootloader went away" case.
        server.volume = lambda: "NICENANO"
        server.ports = lambda: []
        server.wait_for = lambda fn, t: "cu.usbmodem1401"
        server.load_state = lambda: {"half_serials": {"right": "RIGHTSERIAL"}}
        server.remember_half = lambda side, port: None
        flashed = []
        server.flash = lambda side, port: flashed.append(port) or False

        # The LEFT half passes the first check, its write fails, and the board
        # that comes back for the retry is the RIGHT one -> refuse, do not flash.
        serials = iter(["LEFTSERIAL", "RIGHTSERIAL"])
        server.port_serial = lambda port: next(serials, "RIGHTSERIAL")
        assert server.flash_half("left") is False
        assert len(flashed) == 1, f"flashed after refusing: {flashed}"
        assert "right half" in server.STATE["error"], server.STATE["error"]

        # Same shape, but the LEFT half comes back -> the retry proceeds.
        flashed.clear()
        server.port_serial = lambda port: "LEFTSERIAL"
        assert server.flash_half("left") is False      # flash() never succeeds here
        assert len(flashed) > 1, "retry never happened after the re-wait"
        print("retry-rewait self-check: 3 passed")
    finally:
        (server.volume, server.ports, server.port_serial, server.load_state,
         server.flash, server.wait_for, server.remember_half) = real


main()
half_identity()
deploy_lock()
retry_rewait()
