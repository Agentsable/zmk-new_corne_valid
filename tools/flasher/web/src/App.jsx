import { useCallback, useEffect, useState } from "react";
import Deploy from "./Deploy.jsx";
import Keymap from "./Keymap.jsx";
import RequestCard from "./Request.jsx";
import Verify from "./Verify.jsx";
import Workflow from "./Workflow.jsx";

const NAV = [
  { id: "deploy", label: "Firmware update" },
  { id: "current", label: "Current keymap" },
  { id: "pending", label: "Update request" },
  { id: "workflow", label: "Deployment workflow" },
  { id: "verify", label: "Source verification" },
];

export default function App() {
  const [page, setPage] = useState("deploy");
  const [req, setReq] = useState(null);

  const refresh = useCallback(() => {
    fetch("/api/state").then((r) => r.json()).then((j) => setReq(j.request)).catch(() => {});
  }, []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Eyelash Corne</div>
        <nav>
          {NAV.map((n) => (
            <button key={n.id} className={page === n.id ? "on" : ""}
              onClick={() => setPage(n.id)}>
              {n.label}
              {n.id === "pending" && req?.open && <span className="dot" />}
            </button>
          ))}
        </nav>
      </aside>

      <main className="content">
        {page === "deploy" && <Deploy />}
        {page === "verify" && <Verify />}
        {page === "workflow" && <Workflow />}

        {page === "current" && (
          <div className="page">
            <h1>Current keymap</h1>
            {req?.last
              ? <RequestCard at={req.last.at} description={req.last.description}
                  label="Last update deployed" />
              : <p className="blurb">No deployment recorded yet.</p>}
            <Keymap source="current" />
          </div>
        )}

        {page === "pending" && (
          <div className="page">
            <h1>Update request</h1>
            {req?.open
              ? <RequestCard at={req.at} description={req.description} />
              : <>
                  <p className="none">No pending update request.</p>
                  {req?.last && <RequestCard at={req.last.at}
                    description={req.last.description} label="Last update deployed" />}
                </>}
            <p className="blurb">Click any key to change its binding, then save to open a new request.</p>
            <Keymap source="pending" editable onSaved={refresh} />
          </div>
        )}
      </main>
    </div>
  );
}
