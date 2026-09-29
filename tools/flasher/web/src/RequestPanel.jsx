import { useCallback, useEffect, useState } from "react";

// The bundle this page was loaded from. A tab left open across a rebuild keeps
// running the old code; the server compares this and refuses to deploy for it.
const BUILD = import.meta.url.split("/").pop();

/** Right-hand panel: everything queued for the next firmware update.
 *
 * Two kinds of change live here. Pending edits are in the browser and not yet
 * written to the keymap. Committed changes are already on disk and are what
 * the board is actually missing -- the server decides that by comparing the
 * keymap against the last deploy, so the panel cannot disagree with reality.
 */
export default function RequestPanel({ pending = [], onAdd, onDiscard, onSaved, busy }) {
  const [req, setReq] = useState(null);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState("");

  const refresh = useCallback(() => {
    fetch("/api/state").then((r) => r.json()).then(setReq).catch(() => {});
  }, []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, [refresh]);

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
    const r = await fetch("/api/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, build: BUILD }),
    });
    const j = await r.json().catch(() => ({}));
    setStarting(false);
    if (j.error) setErr(j.error); else location.hash = "deploy";
  };

  const nothing = !pending.length && !onDisk;

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
            <button className="primary" disabled={busy} onClick={onAdd}>
              {busy ? "Adding…" : "Add to request"}
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

      <div className="rp-foot">
        <span className="rp-name" title={name}>{name}</span>
        <button className="primary" disabled={nothing || running || starting} onClick={send}>
          {running ? "Update running…" : starting ? "Starting…" : "Send update request"}
        </button>
        {err && <p className="err">{err}</p>}
        <p className="blurb">Starts the firmware update. Both halves need a double-tap.</p>
      </div>
    </aside>
  );
}
