import { useEffect, useState } from "react";

const LABEL = {
  blank: "not started",
  red: "waiting — double-tap reset",
  orange: "bootloader mounted, flashing",
  green: "flashed",
};

function Side({ name, status, order }) {
  return (
    <div className={"side " + status}>
      <span className="side-name">{name}<span className="order">{order}</span></span>
      <span className="side-status">{LABEL[status]}</span>
    </div>
  );
}

export default function Deploy() {
  const [s, setS] = useState(null);
  const [name, setName] = useState("");
  useEffect(() => {
    const tick = async () => { try { setS(await (await fetch("/api/state")).json()); } catch {} };
    tick();
    const id = setInterval(tick, 700);
    return () => clearInterval(id);
  }, []);
  if (!s) return <div className="page" />;

  const running = !["idle", "error", "done"].includes(s.phase);
  const when = s.request.at
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
      <button className="request" disabled={running}
        onClick={() => fetch("/api/start", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }) })}>
        <span className="req-when">Update requested {when}</span>
        <span className="req-desc">{s.request.description}</span>
      </button>

      <div className="sides">
        <Side name="Right" status={s.right} order="1st" />
        <Side name="Left" status={s.left} order="2nd" />
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
      {s.phase === "done" && (
        <button className="push" disabled={s.push === "ok"}
          onClick={() => fetch("/api/push", { method: "POST" })}>
          {s.push === "ok" ? "Pushed to git" : "Push update to git"}
        </button>
      )}
      {s.push_msg && <p className={s.push === "ok" ? "ok" : "err"}>{s.push_msg}</p>}
    </div>
  );
}
