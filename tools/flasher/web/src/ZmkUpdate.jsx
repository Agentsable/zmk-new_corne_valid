import { useState } from "react";

/** Reasons the read can fail that are the user's to resolve, not bugs. */
const HINTS = {
  busy: "zmk.studio is holding the serial port. Disconnect it there, then read again.",
  locked: "Hold the right half's outer thumb key (MO(3)) and tap Esc on the left half, then read again.",
  no_port: "Plug the left half in over USB.",
  no_deps: "Delete tools/flasher/.venv and run run.sh again to reinstall dependencies.",
};

export default function ZmkUpdate() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [km, setKm] = useState(null);

  async function read() {
    setBusy(true); setErr(null); setKm(null);
    try {
      const r = await fetch("/api/zmk/read", { method: "POST" });
      const j = await r.json();
      if (r.ok) setKm(j.keymap); else setErr(j);
    } catch (e) {
      setErr({ kind: "failed", error: String(e) });
    }
    setBusy(false);
  }

  const layers = km?.layers ?? [];
  return (
    <div className="page">
      <h1>ZMK update</h1>
      <p className="blurb">
        Reads the keymap the board is actually running — the one ZMK Studio stored in
        its memory, which can differ from the committed source every other page shows.
        The keyboard must be unlocked, and zmk.studio must not be connected.
      </p>

      <div>
        <button className="primary" onClick={read} disabled={busy}>
          {busy ? "Reading…" : "Read board keymap"}
        </button>
      </div>

      {err && (
        <div className="card">
          <p className="err">{err.error}</p>
          {HINTS[err.kind] && <p className="blurb">{HINTS[err.kind]}</p>}
        </div>
      )}

      {km && (
        <div className="card">
          <p className="ok">Read {layers.length} layers from the board.</p>
          <ol className="steps">
            {layers.map((l, i) => (
              <li key={l.id ?? i} className="done">
                <span className="sdot" />
                <span className="slabel">{l.name || `Layer ${i}`}</span>
                <code className="sdetail">{(l.bindings ?? []).length} bindings</code>
              </li>
            ))}
          </ol>
          <p className="blurb">
            Raw read only. The per-layer diff against source, with red/orange marking and
            per-key adopt, is not built yet — it needs this data shape confirmed first.
          </p>
        </div>
      )}
    </div>
  );
}
