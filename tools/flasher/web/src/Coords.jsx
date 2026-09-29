import { useEffect, useState } from "react";

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
      .then((j) => setG({ layout: j.layout, rc: j.rc, keys: j.layers?.[0]?.keys ?? [] }))
      .catch(() => {});
  }, []);
  if (!g?.layout?.length) return <div className="page"><h1>Key coordinates</h1></div>;

  const { layout, rc, keys } = g;
  const xs = layout.map((p) => p[0]);
  const split = (Math.min(...xs) + Math.max(...xs)) / 2;
  const half = (i) => (layout[i][0] < split ? "L" : "R");

  // The joystick and rotary share matrix rows with ordinary keys, so counting
  // them as columns shifts every alpha along: the right half would start at
  // R0-1, and joystick-right would sort ahead of the right thumbs. They get
  // names instead, and the grid is numbered without them.
  const JOY = { up: "JOY↑", down: "JOY↓", left: "JOY←", right: "JOY→", centre: "JOY•" };
  const special = (i) => {
    const k = keys[i] ?? {};
    if (k.rotary) return "ROT";
    if (k.joy) return JOY[k.joy] ?? "JOY";
    return null;
  };

  const col = {};
  const buckets = {};
  layout.forEach((_, i) => {
    if (special(i)) return;
    const k = `${half(i)}${rc[i][0]}`;
    (buckets[k] ??= []).push(i);
  });
  Object.values(buckets).forEach((list) => {
    list.sort((a, b) => layout[a][0] - layout[b][0]);
    list.forEach((i, n) => { col[i] = n; });
  });

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
                <text className={"clab" + (special(i) ? " sp" : "")}
                      x={x + W / 2} y={y + H / 2 - 4}>
                  {special(i) ?? `${half(i)}${rc[i][0]}-${col[i]}`}
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
