/** Identity of the bundle this code is running from.
 *
 * /api/start refuses a request whose build hash is not the one the server is
 * serving: a tab left open across a rebuild posts straight through, skips the
 * save, and flashes a keymap without the queued edits in it. Vite emits one
 * bundle, so import.meta.url is the same filename current_build() reads off
 * disk.
 *
 * This lives in a shared module because forgetting to send it does not fail
 * loudly -- it returns a 409 that looks exactly like the button doing nothing.
 * Two of the three deploy buttons shipped that way and neither could ever
 * start a deploy.
 */
export const BUILD = import.meta.url.split("/").pop();

/** POST /api/start. Always returns a reason instead of throwing or going quiet. */
export async function startDeploy(name) {
  try {
    const r = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, build: BUILD }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) {
      return { ok: false, error: j.error || `The flasher refused the request (${r.status}).` };
    }
    return { ok: true, ...j };
  } catch (e) {
    return { ok: false, error: `Could not reach the flasher: ${e}` };
  }
}
