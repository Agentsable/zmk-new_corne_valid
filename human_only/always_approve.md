# Always approve

Standing authorization from the repo owner. Claude runs anything in this file
without asking, every time, in any session. Nothing here needs re-confirming.

Granted 2026-09-29.

## Running a build

Everything involved in producing firmware — dispatching, watching, downloading,
building locally — is pre-approved.

    gh workflow run build.yml            # fork builds do NOT trigger on push; always dispatch
    gh workflow run build.yml --ref <branch>
    gh run list --workflow=build.yml
    gh run watch <run-id>
    gh run view <run-id> --log-failed
    gh run download <run-id>

Committing and pushing config changes is part of running a build: the workflow
builds what is on the remote, so an un-pushed keymap edit is not in the firmware.
Pre-approved for `config/`, `boards/`, `build.yaml`, `keymap-drawer/`.

Local builds via the flasher's Docker `west build` are pre-approved:

    tools/flasher/run.sh
    tools/flasher/deploy.py "version name"

## Still ask

Flashing the hardware itself. `deploy.py` tags, pushes, and writes firmware to
both halves over serial DFU — that one gets confirmed each time.

Anything touching `human_only/`. See CLAUDE.md.
