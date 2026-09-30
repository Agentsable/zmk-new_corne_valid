import { useCallback, useEffect, useState } from "react";
import useFlasherState from "./useFlasherState.js";
import { startDeploy } from "./start.js";
import { queueAdd, queueClear, queueFlush, queueList } from "./queue.js";

/** Right-hand panel: everything queued for the next firmware update.
 *
 * Two kinds of change live here. Pending edits are in the browser and not yet
 * written to the keymap. Committed changes are already on disk and are what
 * the board is actually missing -- the server decides that by comparing the
 * keymap against the last deploy, so the panel cannot disagree with reality.
 */
export default function RequestPanel({ pending = [], onAdd, onDiscard, onSaved, busy }) {
  const req = useFlasherState();
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState("");
  const [queued, setQueued] = useState([]);
  const [qbusy, setQbusy] = useState(false);
  const down = Boolean(req?.local_down);

  const loadQueue = useCallback(async () => {
    const r = await queueList();
    setQueued(r.ok ? (r.items ?? []) : []);
  }, []);
  useEffect(() => { loadQueue(); }, [loadQueue, down]);

  // With the Mac off there is nothing to write to, so park the edits in the
  // worker against the sha they were composed on.
  const stash = async () => {
    setQbusy(true); setErr("");
    const sha = req?.request?.sha || "";
    for (const p of pending) {
      const r = await queueAdd({ layer: p.layer, index: p.index,
                                 binding: p.binding, coord: p.coord ?? null,
                                 base_sha: sha });
      if (!r.ok) { setErr(r.error || "Could not queue the change."); break; }
    }
    await loadQueue();
    setQbusy(false);
    onDiscard?.();
  };

  const applyQueue = async () => {
    setQbusy(true); setErr("");
    const r = await queueFlush();
    if (!r.ok) {
      setErr(r.kind === "conflict"
        ? "The keymap changed since these were queued, so nothing was written. "
          + "Discard them and make the changes again."
        : (r.error || "Could not apply the queued changes."));
    } else {
      onSaved?.();
    }
    await loadQueue();
    setQbusy(false);
  };

  const dropQueue = async () => {
    setQbusy(true);
    await queueClear();
    await loadQueue();
    setQbusy(false);
  };

  const running = req && !["idle", "error", "done"].includes(req.phase);
  const onDisk = req?.request?.open;

  // The version name is built from the changes themselves, so a release is
  // named after what it contains rather than whatever someone typed.
  // The name is the only record of what a release contained, so it carries the
  // layer too -- without it a recovered request cannot be replayed. Truncation
  // drops whole entries and says how many, rather than slicing one in half and
  // losing a binding entirely.
  const parts = [];
  if (onDisk && req.request.description) parts.push(req.request.description);
  for (const p of pending) {
    parts.push(`${p.layer} ${p.coord ?? p.index} ${p.binding.replace(/^&/, "")}`);
  }
  let name = "";
  let dropped = 0;
  for (const part of parts) {
    const next = name ? `${name}, ${part}` : part;
    if (next.length > 80) { dropped += 1; continue; }
    name = next;
  }
  if (dropped) name += ` +${dropped} more`;
  name ||= "keymap update";

  const send = async () => {
    setStarting(true); setErr("");
    // Write anything still in the browser FIRST. Deploying without this flashes
    // whatever is on disk and silently discards the queued edits -- which is
    // exactly what happened on 22:38: a release named after seven changes that
    // contained none of them.
    if (pending.length) {
      const s = await fetch("/api/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: name,
          edits: pending.map((p) => ({ layer: p.layer, index: p.index, binding: p.binding })),
        }),
      });
      const sj = await s.json().catch(() => ({}));
      if (!s.ok || sj.error) {
        setStarting(false);
        setErr(sj.error || "Could not write the changes; nothing was flashed.");
        return;
      }
      onSaved?.();
    }
    const r = await startDeploy(name);
    setStarting(false);
    if (!r.ok) setErr(r.error); else location.hash = "deploy";
  };

  const nothing = !pending.length && !onDisk && !queued.length;

  return (
    <aside className="reqpanel">
      <h2>Update request</h2>

      {nothing && <p className="blurb">No changes queued. The board matches source.</p>}

      {pending.length > 0 && (
        <>
          <span className="rp-head">Not yet written ({pending.length})</span>
          <ul className="rp-list">
            {pending.map((p) => (
              <li key={`${p.layer}:${p.index}`}>
                <code className="rp-coord">{p.coord ?? p.index}</code>
                <span className="rp-layer">{p.layer}</span>
                <code className="rp-bind">{p.binding}</code>
              </li>
            ))}
          </ul>
          <div className="rp-actions">
            <button className="primary" disabled={busy || qbusy}
                    onClick={down ? stash : onAdd}>
              {busy || qbusy ? "Adding…" : down ? "Queue until connected" : "Add to request"}
            </button>
            <button onClick={onDiscard}>Discard</button>
          </div>
        </>
      )}

      {onDisk && (
        <>
          <span className="rp-head">On disk, awaiting flash</span>
          <p className="rp-desc">{req.request.description}</p>
        </>
      )}

      {queued.length > 0 && (
        <>
          <span className="rp-head">Queued offline ({queued.length})</span>
          <ul className="rp-list">
            {queued.map((q) => (
              <li key={`${q.layer}:${q.index}`}>
                <code className="rp-coord">{q.coord ?? q.index}</code>
                <span className="rp-layer">{q.layer}</span>
                <code className="rp-bind">{q.binding}</code>
              </li>
            ))}
          </ul>
          <div className="rp-actions">
            <button className="primary" disabled={qbusy || down} onClick={applyQueue}>
              {qbusy ? "Applying…" : down ? "Waiting for the flasher" : "Apply queued changes"}
            </button>
            <button disabled={qbusy} onClick={dropQueue}>Discard</button>
          </div>
        </>
      )}

      <div className="rp-foot">
        <span className="rp-name" title={name}>{name}</span>
        <button className="primary"
                disabled={nothing || running || starting || down} onClick={send}>
          {running ? "Update running…" : starting ? "Starting…" : "Send update request"}
        </button>
        {err && <p className="err">{err}</p>}
        <p className="blurb">Starts the firmware update. Both halves need a double-tap.</p>
      </div>
    </aside>
  );
}
