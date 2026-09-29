# Hosted flasher

Two hostnames, pointing opposite ways:

| Hostname | What answers | Reachable by |
|---|---|---|
| `keys.hyperdev.app` | this Worker: the built UI, plus `/api/*` proxied to the Mac | you, after signing in |
| `flasher.hyperdev.app` | cloudflared tunnel to `127.0.0.1:8787` on the Mac | only this Worker |

One origin on purpose. The browser only ever talks to `keys.hyperdev.app`, so
there is no CORS and no third-party cookie to lose.

## Running the local half

    tools/flasher/connect.sh

Starts `server.py` if it is not already up, then the tunnel. Leave it open; the
indicator in the top right of the hosted app goes green within a few seconds.

## Auth

Two gates, and neither is Cloudflare Access -- both available API tokens are
forbidden from configuring it, so Access has to be added from the Zero Trust
dashboard. Nothing here has to change when it is.

- **Browser to Worker**: HTTP Basic on `/api/*`, `/queue*` and `/login`.
  Credentials live in the gitignored `tools/flasher/.hosted-secrets.json`.
  Sign in once at `/login`; the browser carries it from then on.
- **Worker to Mac**: `X-Flasher-Secret`, checked by `server.py` on anything
  arriving with a `Cf-Ray` header. Without it the tunnel hostname is inert.

Only `/login` may answer with `WWW-Authenticate`. A browser meets that header
with a native dialog, and a `fetch()` behind that dialog never settles -- the
polling indicator would freeze on its last value instead of reporting the truth.

## Deploying

    cd tools/flasher/web && npm run build
    cd ../worker && npx wrangler deploy

This happens automatically on `git push` via `.githooks/pre-push`, but only when
something under `tools/flasher/web/` or `tools/flasher/worker/` changed.

A fresh clone must opt in, because hooks are not cloned:

    git config core.hooksPath .githooks

Pushes do not trigger GitHub Actions on this fork, which is why deployment hangs
off a local hook rather than CI. Cloudflare Workers Builds would do it
server-side, but needs their GitHub App installed from the dashboard.
