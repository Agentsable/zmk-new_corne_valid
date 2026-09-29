import { useState } from "react";

/** Failures the user resolves, not bugs to debug. */
const HINTS = {
  busy: "zmk.studio is holding the serial port. Disconnect it there, then read again.",
  locked: "Hold the right half's outer thumb key (MO(3)) and tap Esc on the left half, then read again.",
  no_port: "Plug the left half in over USB.",
  no_deps: "Delete tools/flasher/.venv and run run.sh again to reinstall dependencies.",
};

/** One key. Red on the source side, orange on the board side, grey once settled. */
function Key({ k, side, onPick, picked }) {
  const mark = k.unknown ? "unknown"
    : !k.changed ? ""
    : k.rejected ? "rejected"
    : side === "source" ? "was" : "now";
  const text = (side === "source" ? k.source : k.board) ?? "—";
  const live = k.changed && !k.rejected;
  return (
    <button
      className={`zkey ${mark} ${picked ? "picked" : ""}`}
      disabled={!live}
      title={k.unknown
        ? `${k.source} — the board reports a value its metadata gives no name for, so it cannot be compared`
        : live ? `${k.source}  →  ${k.board}` : text}
      onClick={() => live && onPick(k)}
    >
      {text.replace(/^&/, "")}
    </button>
  );
}

function LayerPair({ layer, onPick, picked }) {
  const { keys } = layer;
  return (
    <div className="zlayer">
      <div className="zlayer-head">
        <span className="slabel">{layer.source_name ?? layer.board_name}</span>
        {layer.changed > 0
          ? <code className="sdetail">{layer.changed} to decide</code>
          : <code className="sdetail ok">in sync</code>}
        {layer.unknown > 0 && <code className="sdetail">{layer.unknown} unreadable</code>}
      </div>
      <div className="zpair">
        <div className="card">
          <h2>Current source</h2>
          <div className="zgrid">
            {keys.map((k) => (
              <Key key={k.index} k={k} side="source" onPick={onPick}
                   picked={picked === `${layer.index}/${k.index}`} />
            ))}
          </div>
        </div>
        <div className="card">
          <h2>On the board</h2>
          <div className="zgrid">
            {keys.map((k) => (
              <Key key={k.index} k={k} side="board" onPick={onPick}
                   picked={picked === `${layer.index}/${k.index}`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ZmkUpdate() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [layers, setLayers] = useState(null);
  const [sel, setSel] = useState(null);

  async function read() {
    setBusy(true); setErr(null); setSel(null);
    try {
      const r = await fetch("/api/zmk/read", { method: "POST" });
      const j = await r.json();
      if (r.ok) { setLayers(j.layers); } else { setErr(j); setLayers(null); }
    } catch (e) {
      setErr({ kind: "failed", error: String(e) });
    }
    setBusy(false);
  }

  async function decide(adopt) {
    if (!sel) return;
    const r = await fetch("/api/zmk/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: sel.key, adopt, binding: sel.k.board }),
    });
    const j = await r.json();
    if (!r.ok) { setErr(j); return; }
    setSel(null);
    // adopting rewrites source, so the diff has to come from the board again
    if (adopt) await read(); else await read();
  }

  const total = (layers ?? []).reduce((n, l) => n + l.changed, 0);

  return (
    <div className="page">
      <h1>ZMK update</h1>
      <p className="blurb">
        Compares the keymap the board is running — the one ZMK Studio stored in its
        memory — against the committed source. Adopting a key rewrites
        config/eyelash_corne.keymap; the board only matches again once you flash.
        The keyboard must be unlocked and zmk.studio must not be connected.
      </p>

      <div className="zbar">
        <button className="primary" onClick={read} disabled={busy}>
          {busy ? "Reading…" : layers ? "Re-read board" : "Read board keymap"}
        </button>
        {layers && (
          <span className="blurb">
            {total > 0 ? `${total} keys differ` : "source and board agree"}
          </span>
        )}
      </div>

      {layers && (
        <p className="zlegend">
          <span className="zkey was">was</span> source
          <span className="zkey now">now</span> board
          <span className="zkey unknown">—</span>
          unnameable: the joystick keys send a packed value the device metadata
          gives no name for, so they cannot be compared either way. Not a difference.
        </p>
      )}

      {err && (
        <div className="card">
          <p className="err">{err.error}</p>
          {HINTS[err.kind] && <p className="blurb">{HINTS[err.kind]}</p>}
        </div>
      )}

      {sel && (
        <div className="card zdecide">
          <span className="slabel">
            <code>{sel.k.source}</code> → <code>{sel.k.board}</code>
          </span>
          <button className="primary" onClick={() => decide(true)}>Adopt the board's</button>
          <button onClick={() => decide(false)}>Keep source</button>
          <button onClick={() => setSel(null)}>Cancel</button>
        </div>
      )}

      {layers?.map((l) => (
        <LayerPair key={l.index} layer={l} picked={sel?.key}
          onPick={(k) => setSel({ key: `${l.index}/${k.index}`, k })} />
      ))}
    </div>
  );
}
