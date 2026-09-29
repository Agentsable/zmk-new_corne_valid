import { useCallback, useEffect, useState } from "react";

/** Right-hand panel: everything queued for the next firmware update.
 *
 * Two kinds of change live here. Pending edits are in the browser and not yet
 * written to the keymap. Committed changes are already on disk and are what
 * the board is actually missing -- the server decides that by comparing the
 * keymap against the last deploy, so the panel cannot disagree with reality.
 */
export default function RequestPanel({ pending = [], onAdd, onDiscard, busy }) {
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
  const parts = [];
  if (onDisk && req.request.description) parts.push(req.request.description);
  for (const p of pending) parts.push(`${p.coord ?? p.index} ${p.binding.replace(/^&/, "")}`);
  const name = parts.join(", ").slice(0, 90) || "keymap update";

  const send = async () => {
    setStarting(true); setErr("");
    const r = await fetch("/api/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
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
