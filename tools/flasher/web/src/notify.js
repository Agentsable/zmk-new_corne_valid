/* Chrome notifications for the moments that need the user: a half waiting for a
   double-tap, a finished or failed deployment, and a newly pending request.
   Fired on transitions only -- polling every 700ms would otherwise spam. */

export function canNotify() {
  return typeof Notification !== "undefined";
}

export function permission() {
  return canNotify() ? Notification.permission : "unsupported";
}

export async function askPermission() {
  if (!canNotify()) return "unsupported";
  return Notification.requestPermission();
}

function fire(title, body, tag) {
  if (!canNotify() || Notification.permission !== "granted") return;
  try {
    // same tag replaces an older notification instead of stacking duplicates
    new Notification(title, { body, tag, requireInteraction: tag === "action" });
  } catch { /* notifications can be blocked per-site */ }
}

/** Compare two polls and fire for whatever just changed. */
export function notifyOnChange(prev, next) {
  if (!prev || !next) return;

  if (prev.phase !== next.phase) {
    if (next.phase === "right_wait")
      fire("Right half ready", "Double-tap reset on the RIGHT half to flash it.", "action");
    else if (next.phase === "left_wait")
      fire("Left half ready", "Double-tap reset on the LEFT half to flash it.", "action");
    else if (next.phase === "build")
      fire("Building firmware", "Predeploy pushed. Building both halves.", "progress");
    else if (next.phase === "done")
      fire("Deployment complete", next.version?.deployed || "Both halves programmed.", "result");
    else if (next.phase === "error")
      fire("Deployment failed", next.error || "See the workflow page.", "result");
  }

  const was = prev.request?.open, now = next.request?.open;
  if (!was && now)
    fire("Update request pending", next.request?.description || "A keymap change is waiting to be flashed.", "request");
}
