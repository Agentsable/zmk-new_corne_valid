import { useCallback, useEffect, useState } from "react";

export default function Verify() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(() => {
    setBusy(true);
    fetch("/api/verify").then((r) => r.json()).then(setD).finally(() => setBusy(false));
  }, []);
  useEffect(run, [run]);

  return (
    <div className="page">
      <h1>Source verification</h1>
      <p className="blurb">
        Re-reads the firmware sources and confirms every value the app renders traces
        back to them. Nothing here is cached.
      </p>
      <div className="vrow">
        <button className="primary" disabled={busy} onClick={run}>
          {busy ? "Running…" : "Run checks"}
        </button>
        {d && <span className={"vscore " + (d.passed === d.total ? "ok" : "bad")}>
          {d.passed}/{d.total} passed
        </span>}
        {d?.sha && <code className="vsha">{d.path} · {d.sha}</code>}
      </div>
      {d?.error && <p className="err">{d.error}</p>}
      <ul className="checks">
        {d?.checks?.map((c) => (
          <li key={c.name} className={c.ok ? "pass" : "fail"}>
            <span className="badge">{c.ok ? "PASS" : "FAIL"}</span>
            <div>
              <div className="cname">{c.name}</div>
              <div className="cdetail">{c.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
