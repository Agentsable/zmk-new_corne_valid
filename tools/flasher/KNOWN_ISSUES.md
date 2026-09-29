# Known issues and where to look next

State as of 2026-09-30. Everything here was observed, not guessed; each entry
says how it was seen so it can be re-checked rather than re-argued.

The pattern worth carrying: every failure this tool has had looked like success.
A push that deployed nothing printed nothing. An indicator froze on its last
value instead of reporting the truth. A release was named after seven changes it
did not contain. Prefer checks that fail loudly over states that merely look
fine.

## Open

### 1. The offline edit queue has no UI — feature unreachable
The Worker implements `/queue` (add, list, flush, clear) with the `base_sha`
conflict guard, and all of it works over curl. **Nothing in `web/src` calls it**
(`grep -rn "/queue" web/src` is empty). Composing edits while the Mac is off —
the behaviour chosen when this was designed — cannot be done from the browser.

### 2. Offline data is not marked stale — highest risk here
The Worker returns `stale: true` and `stale_at` when serving the KV cache, and
**no component reads either** (`grep -rn "stale" web/src` is empty). With the Mac
off, "Current keymap" renders cached data that looks live. This is the same
shape as the bugs that already cost two deploys: state that is wrong but
indistinguishable from state that is right.

### 3. `log()` never reaches disk — the audit trail does not survive
`server.py::log` appends to `STATE["log"]`, capped at 200 entries, lost on
restart. `server.log` only ever receives stdout/stderr. So `_audit` ("Record
every mutating request ... unexplained writes should be attributable") and the
`refused remote request` security line both vanish exactly when they would be
needed. Seen by grepping `server.log` for a refusal that had definitely
happened and finding nothing; it was only in `/api/state`.

### 4. Only `&kp`'s parameter is validated
`why_invalid` checks the behaviour for everything and the keycode for `&kp`
only. `&lt 2 SPACEE`, `&mt LSHFT XX` and `&sk XX` still pass and would fail the
build. Same class as the bug fixed in 69788d1, narrower surface. Marked with a
`ponytail:` comment naming the ceiling.

### 5. `&kp EXCL` renders as "EXCL", not `!`
Cosmetic. The display map has no entry for mod-expanded keycodes, so the label
falls back to the raw name. The binding itself is correct.

## Operational gaps (not defects)

- **Cloudflare Access was never configured.** Both API tokens return
  `auth.forbidden` for `access/apps` and `access/service_tokens`; it needs the
  Zero Trust dashboard. Basic auth stands in and nothing has to change when
  Access lands.
- **Auto-deploy only fires from this Mac.** `.githooks/pre-push` builds and
  deploys when `tools/flasher/{web,worker}` changes. Hooks are not cloned: a
  fresh clone needs `git config core.hooksPath .githooks`. Cloudflare Workers
  Builds would make this server-side but needs their GitHub App installed.
- **The Basic auth password has been printed into a session transcript**, and
  `.claude-trace/` exists in this repo. Rotating is a minute: regenerate the
  three values, `wrangler secret put BASIC_USER/BASIC_PASS/LOCAL_SECRET`,
  rewrite `.remote-secret`, restart the server.

## Not bugs, verified

- `&td0` and `&rsr_scrl` validate fine. `zmk_decode.behaviors()` deliberately
  scans the keymap as well as ZMK's dtsi files, so locally-defined behaviours
  are known by design.
- All 192 bindings currently in the keymap pass `why_invalid`. Worth re-running
  after any change to the validator: clicking a key prefills its current
  binding, so a false negative would block re-applying a key unchanged.

## Where bugs are most likely next

Ranked by how little they have been exercised.

1. **ZMK update page** — the serial RPC read/diff/adopt path. It renders, and
   that is all that has ever been checked. Adopting a binding from the board
   writes through `set_bindings`, so it now inherits validation, but the decode
   and diff have not been exercised since the hosted work began.
2. **Flash workflow error paths** — the happy path ran once. Untested: tunnel
   dropping mid-deploy, board unplugged mid-write, `git push` failing at
   predeploy (which pushes *before* building), two clients hitting `/api/start`
   at once.
3. **Queue flush success path** — only the conflict rejection has ever run. A
   flush that actually applies has not.
4. **Build guard, `remote:` branch** — the local-hash and stale-tab branches are
   verified; the hosted-UI branch has never been exercised by a real deploy
   click from `keys.hyperdev.app`.
5. **Source verification and Deployment workflow pages** — render only; output
   never checked for correctness.
6. **Key coordinates page** — labels never cross-checked against the physical
   board, and the whole naming convention rests on them.
7. **`notify.js`** — untouched all session.

## How to hunt

    cd tools/flasher
    python3 test_detect.py        # bootloader detection, 6 checks
    python3 test_bindings.py      # binding validation, both paths + all 192 keys

For the UI, drive Chrome over CDP and **capture console errors**, not just
screenshots — the crashes found this session (`Cannot read properties of null`)
were invisible in a screenshot but loud in `Runtime.exceptionThrown`. Chrome
cannot be scripted here via AppleScript; launch a separate headless instance
with `--remote-debugging-port` and connect with `suppress_origin=True`. Wait for
the port properly: a busy-loop with no sleep returns before Chrome binds.

Test the failure states deliberately, not only the working one. Kill the tunnel
and confirm the indicator turns red rather than freezing. Clear the session and
confirm it says "sign in", not "local app off". Feed the editor a binding that
cannot compile and confirm Apply goes grey.
