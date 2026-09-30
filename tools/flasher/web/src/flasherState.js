/** One poller for /api/state, shared by every component that needs it.
 *
 * There used to be four independent intervals on this endpoint -- App (1500ms),
 * Deploy (700ms), Workflow (700ms) and RequestPanel (1500ms) -- so a single open
 * tab asked the Mac for the same object about 2.6 times a second, each request
 * crossing the Worker and the tunnel. One timer, many subscribers, same data.
 *
 * The period follows the phase: a deploy needs the 700ms cadence to feel live,
 * an idle page does not.
 */
const FAST = 700, SLOW = 1500;
const subs = new Set();
let timer = null, period = 0, latest = null;

function running(s) {
  return s && !["idle", "error", "done"].includes(s.phase);
}

async function tick() {
  let next;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    next = await r.json();
  } catch {
    // Keep the last good value rather than blanking every page; Connection.jsx
    // owns telling the user the local app is unreachable.
    return;
  }
  latest = next;
  for (const fn of subs) fn(next);
  const want = running(next) ? FAST : SLOW;
  if (want !== period) schedule(want);
}

function schedule(ms) {
  period = ms;
  clearInterval(timer);
  timer = setInterval(tick, ms);
}

/** Poll once now, instead of waiting out the current interval. */
export function refreshState() {
  return tick();
}

export function subscribeState(fn) {
  subs.add(fn);
  if (latest) fn(latest);
  if (!timer) { schedule(SLOW); tick(); }
  return () => {
    subs.delete(fn);
    if (!subs.size) { clearInterval(timer); timer = null; period = 0; }
  };
}
