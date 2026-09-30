import { useEffect, useState } from "react";
import { coordLabels } from "./coordLabels.js";

/** A reference card: every key labelled by half, row and column.
 *
 * Rows come from the shield's own matrix (the `rc` the layout derives), not
 * from y -- column stagger means keys in one row sit at different heights, so
 * guessing from geometry would number them wrongly. Columns are counted within
 * each half in physical order, which is how people actually say it.
 *
 * The position index is shown underneath because that, not the coordinate, is
 * what the keymap itself uses: combos take key-positions and edits take an index.
 */
export default function Coords() {
  const [g, setG] = useState(null);
  useEffect(() => {
    fetch("/api/keymap").then((r) => r.json())
      .then((j) => setG({ layout: j.layout, rc: j.rc, keys: j.layers?.[0]?.keys ?? [],
                          stale: j.stale, staleAt: j.stale_at }))
      .catch(() => {});
  }, []);
  if (!g?.layout?.length) return <div className="page"><h1>Key coordinates</h1></div>;

  const { layout, rc, keys } = g;
  const xs = layout.map((p) => p[0]);
  const split = (Math.min(...xs) + Math.max(...xs)) / 2;
  const half = (i) => (layout[i][0] < split ? "L" : "R");

  const labels = coordLabels(layout, rc, keys);
  // These names are what the owner reads out when asking for a change, so a
  // cached copy has to say so -- a name that has moved is worse here than
  // anywhere else on the site.
  const staleAt = g.stale ? new Date(g.staleAt).toLocaleString() : null;
  // coordLabels refuses to guess when the key flags are missing; say so rather
  // than render a board whose every label is off by a column.
  if (!labels.length) {
    return (
      <div className="page">
        <h1>Key coordinates</h1>
        <p className="err">The keymap could not be read, so these keys cannot be
          named. Reload once the flasher is reachable — do not use names from a
          previous view, they may refer to different keys.</p>
      </div>
    );
  }

  const W = 100, H = 100, PAD = 20;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  layout.forEach(([x, y, r, rx, ry]) => {
    const a = ((r || 0) / 100) * (Math.PI / 180);
    const cos = Math.cos(a), sin = Math.sin(a);
    for (const [px, py] of [[x, y], [x + W, y], [x, y + H], [x + W, y + H]]) {
      const dx = px - rx, dy = py - ry;
      const qx = r ? rx + dx * cos - dy * sin : px;
      const qy = r ? ry + dx * sin + dy * cos : py;
      minX = Math.min(minX, qx); minY = Math.min(minY, qy);
      maxX = Math.max(maxX, qx); maxY = Math.max(maxY, qy);
    }
  });

  return (
    <div className="page">
      <h1>Key coordinates</h1>
      {staleAt && (
        <p className="err stale">Cached copy from {staleAt}. The local flasher is
          unreachable, so these names are not known to match the board.</p>
      )}
      <p className="blurb">
        How to name a key when asking for a change: half, matrix row, then column
        within that half counted left to right. The small number is the key's
        position index — what combos and keymap edits actually use.
      </p>
      <div className="card">
        <svg className="board coords"
             viewBox={`${minX - PAD} ${minY - PAD} ${maxX - minX + PAD * 2} ${maxY - minY + PAD * 2}`}>
          {layout.map(([x, y, r, rx, ry], i) => {
            const k = keys[i] ?? {};
            const rot = r ? `rotate(${r / 100} ${rx} ${ry})` : undefined;
            const cls = "ck" + (k.joy ? " joy" : "") + (k.rotary ? " rot" : "");
            return (
              <g key={i} transform={rot}>
                <rect className={cls} x={x + 2} y={y + 2} width={W - 4} height={H - 4} rx={12} />
                <text className={"clab" + (labels[i].special ? " sp" : "")}
                      x={x + W / 2} y={y + H / 2 - 4}>
                  {labels[i].label}
                </text>
                <text className="cpos" x={x + W / 2} y={y + H / 2 + 26}>{i}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="zlegend">
        <span className="zkey" style={{ borderColor: "var(--blue)" }}>joy</span> joystick
        <span className="zkey" style={{ borderColor: "var(--orange)" }}>rot</span> rotary encoder
        — both are real matrix keys and can be bound like any other.
      </p>
    </div>
  );
}
