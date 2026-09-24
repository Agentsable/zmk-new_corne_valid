import { useEffect, useState } from "react";

// server step status -> flag colour
const FLAG = { todo: "blank", run: "orange", fail: "red", ok: "green" };
const FLAG_TITLE = { blank: "not started", orange: "running", red: "failed", green: "done" };

function Flag({ status }) {
  const c = FLAG[status] || "blank";
  return <span className={"flag " + c} title={FLAG_TITLE[c]} aria-label={FLAG_TITLE[c]} />;
}

export default function Workflow() {
  const [s, setS] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const tick = async () => { try { setS(await (await fetch("/api/state")).json()); } catch {} };
    tick();
    const id = setInterval(tick, 700);
    return () => clearInterval(id);
  }, []);

  if (!s) return <div className="page" />;

  const running = !["idle", "error", "done"].includes(s.phase);
  const v = s.version;
  const steps = s.steps || [];

  const start = async () => {
    if (!name.trim()) return;
    setBusy(true);
    await fetch("/api/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    setBusy(false);
  };

  // only the pending version is shown -- no history on this page
  if (!v) {
    return (
      <div className="page">
        <h1>Deployment workflow</h1>
        <p className="none">No pending version.</p>
        <div className="namerow">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Version name, e.g. joystick-tuning"
            onKeyDown={(e) => e.key === "Enter" && start()} />
          <button className="primary" disabled={busy || !name.trim()} onClick={start}>
            {busy ? "Starting…" : "Generate version"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Deployment workflow</h1>
      <div className="vercard">
        <span className="vername">{v.name}</span>
        <div className="vertags">
          <code>{v.predeploy}</code>
          <span className="arrow">→</span>
          <code className={s.phase === "done" ? "done" : ""}>{v.deployed}</code>
        </div>
      </div>

      <ol className="wsteps">
        {steps.map((st, i) => (
          <li key={st.key} className={FLAG[st.status] || "blank"}>
            <Flag status={st.status} />
            <span className="wnum">{i + 1}</span>
            <span className="wlabel">{st.label}</span>
            {st.detail && <code className="wdetail">{st.detail}</code>}
          </li>
        ))}
      </ol>

      {s.error && <p className="err">{s.error}</p>}
      {s.phase === "done" && <p className="ok">Deployment complete.</p>}

      {running && (
        <pre className="wlog">{(s.log || []).slice(-14).join("\n") || "…"}</pre>
      )}

      {!running && (
        <div className="namerow">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="New version name" onKeyDown={(e) => e.key === "Enter" && start()} />
          <button className="primary" disabled={busy || !name.trim()} onClick={start}>
            Generate new version
          </button>
        </div>
      )}
    </div>
  );
}
