import { useState } from "react";
import useFlasherState from "./useFlasherState.js";
import { startDeploy } from "./start.js";

// server step status -> flag colour
const FLAG = { todo: "blank", run: "orange", fail: "red", ok: "green" };
const FLAG_TITLE = { blank: "not started", orange: "running", red: "failed", green: "done" };

function Flag({ status }) {
  const c = FLAG[status] || "blank";
  return <span className={"flag " + c} title={FLAG_TITLE[c]} aria-label={FLAG_TITLE[c]} />;
}

export default function Workflow() {
  const s = useFlasherState();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!s) return <div className="page" />;

  const running = !["idle", "error", "done"].includes(s.phase);
  const v = s.version;
  const steps = s.steps || [];

  // finally, not a trailing setBusy: a rejected fetch used to skip it and freeze
  // the button on "Starting..." for the life of the page.
  const start = async () => {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try {
      const r = await startDeploy(name.trim());
      if (!r.ok) setErr(r.error);
    } finally {
      setBusy(false);
    }
  };

  // only the pending version is shown -- no history on this page
  if (!v) {
    return (
      <div className="page">
        <h1>Deployment workflow</h1>
        {s.local_down ? (
          <p className="err">The local flasher is unreachable, so whether a
            version is pending cannot be read. Start nothing from this page
            until the indicator turns green.</p>
        ) : (
          <p className="none">No pending version.</p>
        )}
        <div className="namerow">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Version name, e.g. joystick-tuning"
            onKeyDown={(e) => e.key === "Enter" && start()} />
          <button className="primary"
            disabled={busy || !name.trim() || Boolean(s.local_down)} onClick={start}>
            {busy ? "Starting…" : "Generate version"}
          </button>
        </div>
        {err && <p className="err">{err}</p>}
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

      {(running || s.phase === "error") && (
        <pre className="wlog">{(s.log || []).slice(-14).join("\n") || "…"}</pre>
      )}

      {!running && (
        <div className="namerow">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="New version name" onKeyDown={(e) => e.key === "Enter" && start()} />
          <button className="primary"
            disabled={busy || !name.trim() || Boolean(s.local_down)} onClick={start}>
            Generate new version
          </button>
        </div>
      )}
      {err && <p className="err">{err}</p>}
    </div>
  );
}
