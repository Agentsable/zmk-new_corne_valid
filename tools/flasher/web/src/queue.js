/** The Worker's offline edit queue.
 *
 * The Worker has implemented /queue (add, list, flush, clear) with a base_sha
 * conflict guard since it was written, and nothing in the UI ever called it --
 * so composing edits while the Mac is off, the behaviour this was designed
 * around, could not be done from a browser at all.
 *
 * Every entry records the keymap sha it was written against. Flushing refuses
 * the whole batch if that sha moved, because replaying an edit onto a
 * different keymap is how a change lands on the wrong binding.
 */
async function call(path, opts) {
  try {
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, status: r.status, ...j };
    return { ok: true, ...j };
  } catch (e) {
    return { ok: false, error: `Could not reach the queue: ${e}` };
  }
}

export const queueList = () => call("/queue");
export const queueClear = () => call("/queue", { method: "DELETE" });
export const queueFlush = () => call("/queue/flush", { method: "POST" });

export const queueAdd = (item) =>
  call("/queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item),
  });
