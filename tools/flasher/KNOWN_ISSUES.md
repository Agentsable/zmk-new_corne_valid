# Known issues and where to look next

State as of 2026-09-30, after a three-way bug hunt over the ZMK serial path,
the layout/coordinate derivation and the flash/deploy machinery.

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

### ~~1. The predeploy tag still does not fully identify the firmware~~ FIXED
The run now **refuses** rather than warning. `dirty_outside_keymap()` is checked
before the build, not after -- Docker has already consumed the working tree by
then -- and `workflow(name, allow_dirty=True)` is the deliberate override.

Parsing this needed `--porcelain -z` read straight from stdout: `git()` strips
its combined output, which eats the leading space of the *first* porcelain line
only. Fixed-width slicing then shifts that one path by a character, and had the
keymap been first it would have stopped matching and the gate would have blocked
the one change the workflow commits itself.

### 2. Nothing checks *which* half is in DFU
`flash_half` waits for any NICENANO mount and writes that side's package. Both
halves are `nice_nano_v2` with identical bootloaders, so double-tapping the
wrong one programmes the wrong firmware, prints `Device programmed.` and marks
the step green. Not detectable from this side.

### ~~3. `deploy.py` has no cross-process guard~~ ALREADY FIXED
`acquire_deploy_lock()` takes `fcntl.flock(LOCK_EX|LOCK_NB)` on
`.deploy.lock` and `workflow()` holds it for the whole run. Exclusive across
processes and released if the holder dies. This entry was stale.

### 4. Layer identity is positional
`keymap_pb2.Layer` carries an `id` that `server.py` drops, so source and board
are paired by array position. `move_layer` in Studio would produce a phantom
diff across every moved layer.

### 5. Orphan predeploy tags accumulate
Nothing deletes a tag. A failed run leaves `predeploy_*` on origin with no
`deployed_*`, and each retry mints a new timestamp.

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
    python3 test_detect.py        # bootloader detection
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
