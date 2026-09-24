#!/usr/bin/env python3
"""Local entry point for a named release -- same workflow the webapp runs.

    ./deploy.py "joystick tuning"

Both entry points call server.workflow(), so a release started from the terminal
and one started from the browser produce identical tags and identical steps.
"""
import sys, time
import server


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    name = " ".join(sys.argv[1:])
    print(f"version name: {name}\nstarted:      {time.strftime(server.VERSION_FMT)}")
    server.workflow(name)
    st = server.STATE
    for s in st["steps"]:
        print(f"  [{s['status']:>4}] {s['label']}  {s['detail']}")
    if st["phase"] == "done":
        print(f"\ndeployed as {st['version']['deployed']}")
        return 0
    print(f"\nfailed: {st['error']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
