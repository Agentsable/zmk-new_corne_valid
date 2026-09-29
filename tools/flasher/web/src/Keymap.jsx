import { useCallback, useEffect, useState } from "react";
import { coordLabels } from "./coordLabels.js";
import RequestPanel from "./RequestPanel.jsx";

const U = 100, GAP = 8, PAD = 24;

function fit(n) { return n <= 4 ? 26 : n <= 6 ? 21 : n <= 8 ? 17 : n <= 11 ? 13 : 11; }

function Key({ pos, k, edited, onPick }) {
  const [x, y, rot, rx, ry] = pos;
  const w = U - GAP, h = U - GAP;
  const cx = rx || x + U / 2, cy = ry || y + U / 2;
  const main = edited ?? k.main;
  const sub = edited ? "" : k.sub;
  const cls = ["key", k.joy && "joy", k.rotary && "rotary",
    !edited && k.main === "▽" && "trans", edited && "edited",
    onPick && "pick"].filter(Boolean).join(" ");
  return (
    <g transform={rot ? `rotate(${rot / 100} ${cx} ${cy})` : undefined}
       className={cls} onClick={onPick}>
      <rect x={x} y={y} width={w} height={h} rx={9} />
      {sub
        ? <>
            <text x={x + w / 2} y={y + h / 2 - 5} className="sub">{sub}</text>
            <text x={x + w / 2} y={y + h / 2 + 17} className="main"
              style={{ fontSize: fit(main.length) }}>{main}</text>
          </>
        : <text x={x + w / 2} y={y + h / 2 + 6} className="main"
            style={{ fontSize: fit(main.length) }}>{main}</text>}
    </g>
  );
}

export default function Keymap({ source, editable, onSaved }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [edits, setEdits] = useState({});
  const [sel, setSel] = useState(null);
  const [draft, setDraft] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  // Whatever is typed is resolved server-side, so the preview and the saved
  // binding come from one place. "=" and "&kp EQUAL" must not disagree.
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    const text = draft.trim();
    if (!text) { setPreview(null); return; }
    let live = true;
    const id = setTimeout(() => {
      fetch("/api/translate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }).then((r) => r.json()).then((j) => { if (live) setPreview(j); })
        .catch((e) => { if (live) setPreview({ ok: false, error: String(e) }); });
    }, 120);
    return () => { live = false; clearTimeout(id); };
  }, [draft]);

  const load = useCallback(() => {
    fetch(`/api/keymap?src=${source}`)
      .then((r) => r.json())
      .then((j) => (j.error ? setErr(j.error) : (setD(j), setErr(""))))
      .catch((e) => setErr(String(e)));
  }, [source]);

  useEffect(() => { setD(null); setEdits({}); setSel(null); load(); }, [load]);

  if (err) return <p className="err">{err}</p>;
  if (!d) return null;

  const maxX = Math.max(...d.layout.map((p) => p[0])) + U;
  const maxY = Math.max(...d.layout.map((p) => p[1])) + U + 30;
  const nEdits = Object.keys(edits).length;

  const apply = () => {
    // store what the server resolved, never the raw text -- typing "=" must
    // put &kp EQUAL in the keymap, not "="
    const binding = preview?.ok ? preview.binding : null;
    if (!binding) {
      // never swallow this: a disabled button with no reason is what made the
      // whole editor look like it silently did nothing
      setErr(preview?.error || "That key could not be resolved — nothing applied.");
      return;
    }
    setErr("");
    setEdits({ ...edits, [`${sel.layer}:${sel.index}`]: binding });
    setSel(null); setDraft(""); setPreview(null);
  };

  const save = async () => {
    setBusy(true);
    const payload = {
      description: desc,
      edits: Object.entries(edits).map(([k, binding]) => {
        const [layer, index] = k.split(":");
        return { layer, index: Number(index), binding };
      }),
    };
    const r = await fetch("/api/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const j = await r.json();
    setBusy(false);
    if (j.error) return setErr(j.error);
    setEdits({}); setDesc(""); load(); onSaved?.();
  };

  const coords = coordLabels(d.layout, d.rc, d.layers[0]?.keys ?? []);

  return (
    <>
      {editable && sel && (
        <div className="editbar">
          <span className="editwho">{sel.layer} · key {sel.index}</span>
          <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && apply()}
            placeholder="a symbol like = or a binding like &kp A" />
          {preview?.ok ? (
            <span className="pv">
              <code className="pv-bind">{preview.binding}</code>
              <span className="pv-key">{preview.main}{preview.sub ? ` ${preview.sub}` : ""}</span>
            </span>
          ) : preview ? (
            <span className="pv err">{preview.error}</span>
          ) : null}
          <button className="primary" onClick={apply}
                  disabled={Boolean(draft.trim()) && !preview?.ok}>Apply</button>
          <button onClick={() => { setSel(null); setDraft(""); }}>Cancel</button>
        </div>
      )}

      {editable && (
        <RequestPanel
          pending={Object.entries(edits).map(([k, binding]) => {
            const [layer, index] = k.split(":");
            return { layer, index: Number(index), binding,
                     coord: coords[Number(index)]?.label };
          })}
          onAdd={save}
          busy={busy}
          onDiscard={() => setEdits({})}
        />
      )}

      {d.layers.map((l) => (
        <section className="card" key={l.name}>
          <h2>{l.name}</h2>
          {d.repo && (
            <a className="srclink" href={`${d.repo}#L${l.line}`}
               target="_blank" rel="noreferrer">
              config/eyelash_corne.keymap:{l.line}
            </a>
          )}
          <svg className="board" viewBox={`${-PAD} ${-PAD} ${maxX + PAD * 2} ${maxY + PAD}`}>
            {d.layout.map((pos, i) => (
              <Key key={i} pos={pos} k={l.keys[i]}
                edited={edits[`${l.name}:${i}`]}
                onPick={editable ? () => {
                  setSel({ layer: l.name, index: i });
                  setDraft(edits[`${l.name}:${i}`] ?? l.keys[i].binding);
                } : undefined} />
            ))}
          </svg>
        </section>
      ))}

      {/* A reference board under the real layers: same geometry, same key
          shapes, but labelled by coordinate instead of binding. Not a ZMK
          layer -- it is how to name a key when asking for a change. */}
      <section className="card">
        <h2>Key coordinates</h2>
        <span className="srclink plain">half · matrix row · column within that half</span>
        <svg className="board" viewBox={`${-PAD} ${-PAD} ${maxX + PAD * 2} ${maxY + PAD}`}>
          {d.layout.map((pos, i) => {
            const c = coords[i];
            const k = d.layers[0]?.keys?.[i] ?? {};
            return (
              <Key key={i} pos={pos}
                   k={{ main: c?.label ?? "", sub: String(i),
                        joy: k.joy, rotary: k.rotary }} />
            );
          })}
        </svg>
      </section>
    </>
  );
}
