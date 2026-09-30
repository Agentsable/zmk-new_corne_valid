import { useEffect, useState } from "react";
import MiniBoard from "./MiniBoard.jsx";
import useFlasherState from "./useFlasherState.js";
import { startDeploy } from "./start.js";

const LABEL = {
  blank: "not started",
  red: "waiting — double-tap reset",
  orange: "bootloader mounted, flashing",
  green: "flashed",
};

function Side({ name, status, order, side, geo }) {
  return (
    <div className={"side " + status}>
      <span className="side-name">{name}<span className="order">{order}</span></span>
      <MiniBoard side={side} geo={geo} />
      <span className="side-status">{LABEL[status]}</span>
    </div>
  );
}

export default function Deploy() {
  const s = useFlasherState();
  const [name, setName] = useState("");
  const [geo, setGeo] = useState(null);
  const [err, setErr] = useState("");
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    // layout plus the joystick/rotary flags, for the per-half diagrams
    fetch("/api/keymap").then((r) => r.json())
      .then((j) => setGeo({ layout: j.layout, keys: j.layers?.[0]?.keys ?? [] }))
      .catch(() => {});
  }, []);
  if (!s) return <div className="page" />;

  const running = !["idle", "error", "done"].includes(s.phase);
  // The worker answers 200 with phase "offline" and both halves "blank" when the
  // Mac is unreachable. Rendering that as-is prints "not started" under a half
  // that may be mid-write, so say what is actually known instead.
  const down = Boolean(s.local_down);

  const send = async () => {
    setStarting(true); setErr("");
    const r = await startDeploy(name);
    setStarting(false);
    if (!r.ok) setErr(r.error);
  };
  // request is absent when the hosted app answers 401 (no session) or reports
  // the Mac offline, so this cannot assume it is there.
  const when = s.request?.at
    ? new Date(s.request.at * 1000).toLocaleString(undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="page">
      <h1>Firmware update</h1>
      <div className="namerow">
        <input value={name} onChange={(e) => setName(e.target.value)} disabled={running}
          placeholder="Version name, e.g. joystick-tuning" />
        <span className="hint">tags as predeploy_&lt;dd-mm-yy_hh-mm&gt;_&lt;name&gt;</span>
      </div>
      <button className="request" disabled={running || starting || down} onClick={send}>
        <span className="req-when">
          {starting ? "Starting…" : `Update requested ${when}`}
        </span>
        <span className="req-desc">{s.request?.description}</span>
      </button>
      {err && <p className="err">{err}</p>}

      {down ? (
        <p className="err">The local flasher is unreachable, so the state of a
          running update cannot be read. What is shown below is not current.</p>
      ) : null}

      <div className={"sides" + (down ? " unknown" : "")}>
        <Side name="Left" status={s.left} order="2nd" side="left" geo={geo} />
        <Side name="Right" status={s.right} order="1st" side="right" geo={geo} />
      </div>

      {s.version && (
        <div className="verbox">
          <code>{s.version.predeploy}</code> → <code>{s.version.deployed}</code>
        </div>
      )}
      {s.steps?.length > 0 && (
        <ol className="steps">
          {s.steps.map((st) => (
            <li key={st.key} className={st.status}>
              <span className="sdot" />
              <span className="slabel">{st.label}</span>
              {st.detail && <code className="sdetail">{st.detail}</code>}
            </li>
          ))}
        </ol>
      )}
      {s.error && <p className="err">{s.error}</p>}
    </div>
  );
}
