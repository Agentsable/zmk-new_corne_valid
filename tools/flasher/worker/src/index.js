/** Hosted front end for the local flasher.
 *
 * One origin serves the built UI and proxies /api/* down a cloudflared tunnel (flasher.hyperdev.app) to
 * the Mac running tools/flasher/server.py. Single origin on purpose: the browser
 * never makes a cross-origin call, so there is no CORS and no third-party cookie
 * to get blocked.
 *
 * The local half is only reachable while the owner's Mac is running the tunnel,
 * so every route has to answer usefully when it is not.
 */

const STALE_KEY = "cache:/api/keymap";       // last parsed keymap seen from the Mac
const STATE_KEY = "cache:/api/state";        // last request/deploy info seen from the Mac
const QUEUE_KEY = "queue:edits";             // offline edits awaiting a live Mac

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

/** cloudflared answers with these when nothing is listening on 8787. */
const DOWN = new Set([502, 503, 504, 521, 522, 523, 525, 530]);

async function callLocal(env, path, init = {}) {
  const headers = new Headers(init.headers || {});
  // Only this Worker knows the shared secret, so the tunnel hostname on its own
  // is useless to anyone who finds it. server.py enforces this on every request
  // carrying Cf-Ray, i.e. everything that arrived through Cloudflare.
  headers.set("X-Flasher-Secret", env.LOCAL_SECRET);
  headers.set("Content-Type", init.body ? "application/json" : "application/json");
  return fetch(env.LOCAL_ORIGIN + path, { ...init, headers, redirect: "manual" });
}

/** Proxy one /api request, and say plainly when the Mac is not there. */
async function proxy(request, url, env) {
  const path = url.pathname + url.search;
  const method = request.method;
  const body = method === "GET" || method === "HEAD"
    ? undefined
    : await request.arrayBuffer();

  let res;
  try {
    res = await callLocal(env, path, { method, body });
  } catch {
    return offline(env, url, "The local flasher is not reachable.");
  }
  if (DOWN.has(res.status)) {
    return offline(env, url, `The local flasher is not running (tunnel said ${res.status}).`);
  }

  const text = await res.text();
  // Cache the parsed keymap whenever we see a good one: it is the only thing
  // that makes the read-only pages useful with the Mac switched off. Parsing
  // lives in keymap.py and is not reimplemented here.
  if (res.ok && method === "GET" && url.pathname.startsWith("/api/keymap")) {
    await env.QUEUE.put(STALE_KEY, JSON.stringify({ at: Date.now(), body: text }));
  }
  // Keep the last request/deploy info too, so the offline pages can say what
  // the board is actually running rather than showing blanks.
  if (res.ok && method === "GET" && url.pathname.startsWith("/api/state")) {
    try {
      const req = JSON.parse(text).request;
      if (req) await env.QUEUE.put(STATE_KEY, JSON.stringify(req));
    } catch { /* a malformed state is not worth failing the request over */ }
  }
  return new Response(text, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") || "application/json",
      "Cache-Control": "no-store",
    },
  });
}

/** What a page gets when the Mac is down: stale truth where we have it. */
async function offline(env, url, why) {
  if (url.pathname.startsWith("/api/keymap")) {
    const hit = await env.QUEUE.get(STALE_KEY, "json");
    if (hit) {
      const data = JSON.parse(hit.body);
      data.stale = true;
      data.stale_at = hit.at;
      return json(200, data);
    }
  }
  if (url.pathname.startsWith("/api/state")) {
    // request is never null on the real endpoint -- request_info() always
    // returns an object, and the pages dereference it without guarding. A shim
    // that answers null crashes the app, so it must honour the same shape.
    const last = await env.QUEUE.get(STATE_KEY, "json");
    return json(200, {
      phase: "offline", left: "blank", right: "blank", log: [], error: "",
      version: null, steps: [], ports: [], volume: null,
      request: last || { open: false, at: 0, description: "", sha: "", last: null },
      local_down: true,
    });
  }
  return json(503, { kind: "local_down", error: why });
}

/** Offline edit queue. Every entry records the keymap it was written against. */
async function queue(request, url, env) {
  const items = (await env.QUEUE.get(QUEUE_KEY, "json")) || [];

  if (request.method === "GET") return json(200, { items });

  if (request.method === "DELETE") {
    await env.QUEUE.put(QUEUE_KEY, JSON.stringify([]));
    return json(200, { ok: true, items: [] });
  }

  if (url.pathname === "/queue/flush") {
    if (!items.length) return json(400, { error: "nothing queued" });

    let st;
    try {
      const r = await callLocal(env, "/api/state");
      if (DOWN.has(r.status)) throw new Error("down");
      st = await r.json();
    } catch {
      return json(503, { kind: "local_down", error: "The local flasher is not running." });
    }

    // The guard that matters. An edit composed against one keymap must not be
    // replayed blind onto a different one -- that is how edits get silently
    // lost or land on the wrong binding.
    const current = st?.request?.sha || "";
    const stale = items.filter((i) => i.base_sha && i.base_sha !== current);
    if (stale.length) {
      return json(409, {
        kind: "conflict", current_sha: current,
        error: "The keymap changed since these edits were queued; nothing was written.",
        conflicts: stale,
      });
    }

    const res = await callLocal(env, "/api/save", {
      method: "POST",
      body: JSON.stringify({
        description: `Queued offline: ${items.map((i) => `${i.layer} ${i.coord ?? i.index}`).join(", ")}`,
        edits: items.map((i) => ({ layer: i.layer, index: i.index, binding: i.binding })),
      }),
    });
    const out = await res.text();
    if (!res.ok) return new Response(out, { status: res.status,
      headers: { "Content-Type": "application/json" } });

    await env.QUEUE.put(QUEUE_KEY, JSON.stringify([]));
    return json(200, { ok: true, applied: items.length, local: JSON.parse(out || "{}") });
  }

  // POST /queue -- add one edit
  let add;
  try { add = await request.json(); } catch { return json(400, { error: "bad json" }); }
  for (const k of ["layer", "index", "binding"]) {
    if (add[k] === undefined || add[k] === null) return json(400, { error: `missing ${k}` });
  }
  const next = items.filter(
    (i) => !(i.layer === add.layer && i.index === add.index)).concat([{
      layer: add.layer, index: Number(add.index), binding: add.binding,
      coord: add.coord ?? null, base_sha: add.base_sha || "", at: Date.now(),
    }]);
  await env.QUEUE.put(QUEUE_KEY, JSON.stringify(next));
  return json(200, { ok: true, items: next });
}

/** Basic auth on everything that can reach the Mac.
 *
 * A native browser affordance rather than a login screen: one prompt, no UI to
 * build, and it is replaceable by Cloudflare Access later without touching the
 * front end. The static pages stay open -- they are read-only and are what makes
 * the app useful with the Mac switched off.
 */
function authorised(request, env) {
  const expect = "Basic " + btoa(`${env.BASIC_USER}:${env.BASIC_PASS}`);
  const got = request.headers.get("Authorization") || "";
  if (got.length !== expect.length) return false;
  // Constant-time-ish compare: do not leak the password through timing.
  let diff = 0;
  for (let i = 0; i < expect.length; i++) diff |= got.charCodeAt(i) ^ expect.charCodeAt(i);
  return diff === 0;
}

/** 401 for an API call, which must NOT carry WWW-Authenticate.
 *
 * A browser meets that header by opening a native auth dialog, and a fetch()
 * behind that dialog never settles -- the polling indicator hangs on its last
 * value instead of reporting the truth. Only /login, a real navigation, gets
 * the challenge; there a prompt is the right affordance, and once it succeeds
 * the browser attaches the credentials to every later request to this origin.
 */
const NEEDS_AUTH = () => new Response(
  JSON.stringify({ kind: "auth", error: "Sign in to reach the local flasher." }), {
    status: 401,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

const CHALLENGE = () => new Response("Sign in to reach the local flasher.\n", {
  status: 401,
  headers: {
    "WWW-Authenticate": 'Basic realm="Eyelash Corne flasher", charset="UTF-8"',
    "Content-Type": "text/plain",
  },
});

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // The one place a native sign-in prompt belongs: a top-level navigation.
    if (url.pathname === "/login") {
      if (!authorised(request, env)) return CHALLENGE();
      return Response.redirect(new URL("/", url).toString(), 302);
    }
    const guarded = url.pathname.startsWith("/api/")
      || url.pathname === "/queue" || url.pathname.startsWith("/queue/");
    if (guarded && !authorised(request, env)) return NEEDS_AUTH();
    if (url.pathname === "/queue" || url.pathname.startsWith("/queue/")) {
      return queue(request, url, env);
    }
    if (url.pathname.startsWith("/api/")) return proxy(request, url, env);
    return env.ASSETS.fetch(request);
  },
};
