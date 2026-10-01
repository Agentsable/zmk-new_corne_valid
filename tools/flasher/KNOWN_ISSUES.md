# Known issues and where to look next

State as of 2026-10-01, after a three-way bug hunt over the ZMK serial path,
the layout/coordinate derivation and the flash/deploy machinery, plus a
follow-up pass over what that hunt left open.

The pattern worth carrying: every failure this tool has had looked like success.
A push that deployed nothing printed nothing. An indicator froze on its last
value instead of reporting the truth. A release was named after seven changes it
did not contain. Two deploy buttons could never start a deploy and said nothing
when they failed. A read that obtained zero bytes from the keyboard rendered as
"source and board agree". Prefer checks that fail loudly over states that merely
look fine.

## Fixed in this pass

Grouped by the shape of the failure rather than by file.

### Failures that looked like success
- **Both deploy buttons were dead.** `Deploy.jsx` and `Workflow.jsx` never sent
  the `build` hash, so `/api/start` answered 409 for every click, local and
  hosted. `Deploy.jsx` dropped the promise entirely and `Workflow.jsx` never
  read the response, so nothing was shown either way. `BUILD` and the POST now
  live in `start.js`, which every caller shares and which always returns a
  reason. Verified by intercepting the request in-page: both send the current
  bundle hash and render the refusal.
- **A failed ZMK read rendered as "source and board agree".** `_call` trusted
  proto3 defaults, so a device error, a `lock_state_changed` notification
  landing in the read window, or an empty frame all arrived as a keymap with
  zero layers. It now matches `request_id`, rejects the wrong subsystem, raises
  on `meta.simple_error`, skips notifications, and refuses an empty behaviour
  table or a keymap with no layers.
- **A failed `git show` rendered as a valid keymap.** `/api/keymap?current`
  ignored the exit code; 128 with empty stdout parsed into `layers: []` with a
  full layout, which the coordinate card rendered with 27 of 48 labels
  renumbered. Checked, and `coordLabels()` now refuses to guess without the key
  flags rather than returning shifted names.
- **Three verify checks passed vacuously.** Zero layers compared an empty list
  to an empty list and reported "0 bindings identical on re-parse"; "Layout and
  matrix agree" could only ever be seen passing because `analyse()` raises
  first. They now count what they actually examined and fail on nothing to
  compare.
- **The deployed step discarded two return values.** A failed `git push origin
  main` was invisible: the tag push still shipped the objects, so the page
  printed "Deployment complete." while origin/main pointed at the old keymap.

### State that was wrong but indistinguishable from right
- **Offline data is marked.** The worker's `stale`/`stale_at` had no reader;
  cached keys rendered identically to live ones. `Keymap.jsx` now says so.
- **`Deploy.jsx` and `Workflow.jsx` honour `local_down`.** A tunnel drop
  mid-deploy showed both halves as "not started" and "No pending version."
- **`notify.js` covers the offline transition** and no longer re-fires the
  double-tap prompt when the tunnel recovers.

### Unvalidated input
- **Every checkable behaviour parameter is validated**, not just `&kp`'s.
  `&lt 2 SPACEE`, `&mt LSHFT XX` and `&sk XX` all passed and would have failed
  the build after the predeploy tag was pushed. `PARAMS` in `keymap.py` carries
  the signatures; unknown behaviours still pass on purpose.
- **`known_param` covers the non-keycode headers** (pointing, bt, rgb, outputs)
  plus the keymap's own `#define`s, so `&mmv SLOW_UP` validates and
  `&mmv MOVE_UPP` does not.

### Robustness
- **One deploy path.** `sequence()` never built: it flashed whatever `.zip` was
  left in `PKG_DIR`, then recorded the current keymap as deployed. Deleted;
  unnamed updates run `workflow()` like everything else.
- **Build before push.** A build failure used to leave origin advertising a
  keymap no board runs.
- **`guarded()` wraps the workflow thread.** One escaping exception left the
  phase mid-flight forever and `/api/start` refused everything until restart.
- **Subprocess watchdogs.** `p.wait(timeout=)` was unreachable because
  `for line in p.stdout` blocks first; a stalled build or an nrfutil blocked on
  an unplugged board hung the thread with a live-looking log. `run_streaming()`
  kills the child.
- **`write_timeout` on the serial port**, which defaulted to blocking forever.
- **The flash retry keeps its baseline.** `bootloader_port([])` discarded it and
  could point nrfutil at a board running its firmware.
- **`/api/save` is serialised.** Two concurrent saves lost one set of edits.
- **`log()` reaches disk** (`audit.log`), so the audit trail and the refusal
  lines survive a restart.

### Correctness of the diff
- **`range` parameters are rendered.** `&mmv`/`&msc` are `input_two_axis`, whose
  param1 the firmware declares as RANGE; it was unhandled, so all ten pointer
  keys were permanently "unnameable" and a change to any of them was invisible.
  `MOVE_X`/`MOVE_Y` packing is resolved, with the keymap's
  `ZMK_POINTING_DEFAULT_MOVE_VAL` override winning as `#ifndef` requires.
- **Keycode aliases compare equal.** `encode_alias` follows the `#define` chain,
  so `&kp EXCL` and the board's `LS(N1)` are the same key instead of a permanent
  phantom diff. The same expansion gives `&kp EXCL` the label `!`.
- **Extra board layers and missing bindings are no longer "in sync".**
- **Positional parameter shift fixed**: an empty param1 with a populated param2
  promoted param2 into the first slot.

### Fixed in the follow-up pass
- **A dirty tree is refused, not warned about.** Docker builds the working tree,
  so anything dirty outside the keymap shipped untagged. Checked before the
  build, since Docker has consumed the tree by then; `workflow(allow_dirty=True)`
  is the deliberate override. (From a concurrent session -- see Open 3.)
- **`deploy.py` and the web app exclude each other.** `STATE` is per-process, so
  the `/api/start` gate could not see a terminal run. An `flock` on
  `.deploy.lock` covers both entry points; verified a second process is refused
  and acquires cleanly after release.
- **Layers pair by name, not array position.** `move_layer` is a supported
  Studio RPC, and after a reorder every key in the moved layers read as changed,
  with adopting one writing the wrong binding into the wrong layer. Falls back
  to position when names are not unique, and reports which was used.
- **The wrong half in DFU is refused** once both serials are known -- see Open 2
  for what that does not cover.

### Other
- Four independent `/api/state` pollers became one shared subscriber
  (`flasherState.js`); a single tab went from ~2.6 req/s to ~1.05.
- The offline edit queue has a UI. The worker's `/queue` had no caller at all.
- `layout.py` regexes accept hex `col-offset`, parenthesised negative `rx`/`ry`
  and `RC(0, 0)` with a space; a legal `col-offset` of `0` is no longer read as
  "no right half".
- `restart.sh` kills by listening port. `pkill -f "python server.py"` matched
  nothing, because the macOS framework binary is `Python` with a capital P --
  which is why a fix appeared not to work for two rounds of testing.

## Open

### 1. Orphan predeploy tags are visible but not pruned
Nothing deletes a tag. A failed run leaves `predeploy_*` on origin with no
`deployed_*`, and each retry mints a new timestamp. `orphan_predeploy_tags()`
counts them, a run logs the oldest with the prune command, and `/api/state`
carries the list -- so they can no longer accumulate unnoticed, but removing
them is still manual:

    git tag -d <tag> && git push origin :refs/tags/<tag>

### 2. The first sighting of each half is taken on trust
`check_half()` refuses to flash when the serial in the bootloader is the one
recorded for the *other* half, but nothing in the hardware says "I am the left
half". Until both have been flashed once there is nothing to compare against,
and a wrong double-tap on that very first run records the wrong association.

**This path has never run against a real bootloader.** The logic is unit-tested;
the serial was read from the board in application mode. A bootloader may present
a different USB descriptor, and if its serial differs from the application-mode
one that is still self-consistent (we only ever learn and compare bootloader
serials) -- but it is unverified. Check it on the next real flash.

### 3. Several Claude sessions share this working tree
Found on 2026-09-30: another session running with `--dangerously-skip-permissions`
committed while this one was mid-edit. It staged everything, so it swept up
unrelated in-progress work and shipped it under a message describing only its
own change -- a commit that does not describe its contents, which is the exact
failure this file opens by warning about. It also produced two contradictory
dirty-tree gates in `_workflow`, from two directions, within a minute.

Before editing, check `git log --oneline -3` and `git status`. If another agent
is active, give it a worktree or stop it. A shared tree with two autonomous
writers has no safe merge story.

## Operational gaps (not defects)

- **Cloudflare Access was never configured.** Both API tokens return
  `auth.forbidden` for `access/apps`; it needs the Zero Trust dashboard. Basic
  auth stands in.
- **Auto-deploy only fires from this Mac.** `.githooks/pre-push` deploys when
  `tools/flasher/{web,worker}` changes. Hooks are not cloned: a fresh clone
  needs `git config core.hooksPath .githooks`.
- **The Basic auth password has been printed into a session transcript.**
  Rotating is a minute: regenerate, `wrangler secret put`, rewrite
  `.remote-secret`, restart.

## Verified correct, do not re-investigate

- **All 48 coordinate labels**, traced key-by-key from `.dtsi` geometry through
  the matrix transform and cross-checked against the QWERTY bindings. Three
  independent sources agree. `R20` is index 36 (`&kp N`), the rotary is 34, the
  joystick is 6/19/20/21/35.
- **`flash()`'s success test**: requires the literal `Device programmed.` line
  as well as `rc == 0`.
- **`remote_has_tag`**: correctly refuses to trust a zero exit from `git push`.
- **`/api/start`'s concurrency gate**: phase is read and written under one lock.
- **`save_state`**: tmp file plus `os.replace`, atomic.
- **`_remote_ok`**: `hmac.compare_digest` for both the shared secret and Basic
  auth.
- **Port closing** in `read_board`, via `with _open(port)`.
- All 192 bindings in the committed keymap validate, and the board reads back
  with 0 changed and 0 unknown.

## How to hunt

    cd tools/flasher
    python3 test_detect.py        # bootloader detection, half identity, deploy lock
    python3 test_bindings.py      # binding validation, both paths + all 192 keys
    python3 zmk_diff.py           # diff, mutation, rejection
    python3 -c "import verify,os;print(verify.run(os.path.abspath('../..')))"

For the UI, drive Chrome over CDP and **capture console errors**, not just
screenshots -- this pass introduced a `ReferenceError` that was invisible in a
screenshot and obvious in `Runtime.exceptionThrown`. Chrome cannot be scripted
here via AppleScript; launch a headless instance with `--remote-debugging-port`
and connect with `suppress_origin=True`.

To exercise a deploy button without deploying, override `window.fetch` in the
page and return a synthetic 409. `Network.setBlockedURLs` does **not** work for
this: a blocked request emits no `requestWillBeSent`, so the body cannot be
inspected.

Test the failure states deliberately. Block `/api/state` and confirm the
indicator turns red rather than freezing; drop the auth header and confirm it
says "sign in", not "local app off". Both were checked this pass and both hold.
