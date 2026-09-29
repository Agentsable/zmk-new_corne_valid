import { useCallback, useEffect, useState } from "react";

/** Live/offline indicator for the local flasher, top right of every page.
 *
 * The hosted app is only half a tool: flashing, the serial port and writing the
 * keymap all live on the owner's Mac. This says which half is currently there,
 * and when it is missing it hands over the exact command that brings it back.
 *
 * Three states, not two -- "not logged in" and "Mac is off" both look like a
 * failed fetch but need completely different actions from the reader.
 */

// The flasher lives in a git checkout on one Mac; this is that path. Hardcoded
// deliberately: when the local app is down there is nothing to ask for it.
const REPO = "/Users/yigalweinberger/Documents/Code/home_code/keyborads/zmk-new_corne_valid";
const SCRIPT = `cd ${REPO}/tools/flasher && ./connect.sh`;

const LABEL = {
  live: "Connected",
  down: "Local app off",
  login: "Sign in needed",
  checking: "Checking…",
};

export default function Connection({ onStatus }) {
  const [status, setStatus] = useState("checking");
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const check = useCallback(async () => {
    let next = "down";
    try {
      const r = await fetch("/api/state", { cache: "no-store" });
      const ct = r.headers.get("Content-Type") || "";
      if (r.status === 401 || !ct.includes("json")) {
        // No session for this origin yet. Distinct from "the Mac is off": the
        // fix is signing in, and telling someone to go start a local app they
        // already have running is worse than saying nothing.
        next = "login";
      } else {
        const j = await r.json();
        next = j.local_down ? "down" : "live";
      }
    } catch {
      next = "down";
    }
    setStatus(next);
    onStatus?.(next);
  }, [onStatus]);

  useEffect(() => {
    check();
    const id = setInterval(check, 4000);
    return () => clearInterval(id);
  }, [check]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(SCRIPT);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="conn">
      <button className={`connpill ${status}`} onClick={() => setOpen(!open)}
        title={status === "live" ? "The local flasher is connected"
                                 : "Click for how to connect"}>
        <span className="conndot" />
        {LABEL[status]}
      </button>

      {open && status !== "live" && (
        <div className="connpop">
          {status === "login" ? (
            <>
              <h3>Sign in required</h3>
              <p>This browser has no session for the flasher yet. Sign in once
                 and the browser keeps it for every later request.</p>
              <button className="primary"
                onClick={() => { location.href = "/login"; }}>Sign in</button>
            </>
          ) : (
            <>
              <h3>Start the local app</h3>
              <p>Flashing, the serial port and writing the keymap happen on your
                 Mac. Run this in Terminal and leave the window open:</p>
              <code className="connscript">{SCRIPT}</code>
              <button className="primary" onClick={copy}>
                {copied ? "Copied" : "Copy command"}
              </button>
              <p className="blurb">The indicator turns green within a few seconds
                 of the tunnel connecting.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
