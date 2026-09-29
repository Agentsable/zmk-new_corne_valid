# Project instructions

## `human_only/`

Owner-controlled. It records what the owner has authorized Claude to do, so
Claude must never quietly edit the thing that grants it permission.

- **Read it.** `human_only/always_approve.md` is standing authorization: run
  those things without asking, every session, no re-confirming.
- **Keep it in git.** It is tracked and committed like the rest of the repo;
  never gitignore it, never leave it uncommitted.
- **Ask before changing it.** Every create, edit, rename, or delete under
  `human_only/` needs explicit permission first — including adding a new
  standing approval Claude would benefit from. Propose the exact diff and wait.

Committing an owner-approved change to `human_only/` does not need a second ask;
the approval covered it.

## Build and flash

See `human_only/always_approve.md`. Short version: fork builds never trigger on
push, so always `gh workflow run build.yml`. Flashing is confirmed each time.
