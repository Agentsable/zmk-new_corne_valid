"""Self-check for bootloader detection. Run: python3 test_detect.py"""
import os
os.environ.setdefault("NRFUTIL", ""); os.environ.setdefault("PKG_DIR", "")
import server

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

main()
