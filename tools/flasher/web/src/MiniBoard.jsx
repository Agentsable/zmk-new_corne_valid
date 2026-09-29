/** A small outline of one half, drawn from the same geometry the keymap uses.
 *
 * Nothing here is hand-placed: positions come from layout.analyse, and the
 * joystick and rotary are flagged per key rather than hardcoded by index, so
 * the diagram follows the shield sources if the board ever changes.
 */
const PAD = 14;

export default function MiniBoard({ side, geo }) {
  if (!geo?.layout?.length) return <svg className="mini" viewBox="0 0 10 10" />;

  const { layout, keys } = geo;
  const xs = layout.map((p) => p[0]);
  const split = (Math.min(...xs) + Math.max(...xs)) / 2;

  const idx = layout
    .map((_, i) => i)
    .filter((i) => (layout[i][0] < split ? "left" : "right") === side);
  if (!idx.length) return <svg className="mini" viewBox="0 0 10 10" />;

  const W = 100, H = 100;   // analyse() reports uniform 100x100 units
  const minX = Math.min(...idx.map((i) => layout[i][0]));
  const minY = Math.min(...idx.map((i) => layout[i][1]));
  const maxX = Math.max(...idx.map((i) => layout[i][0])) + W;
  const maxY = Math.max(...idx.map((i) => layout[i][1])) + H;

  return (
    <svg
      className="mini"
      viewBox={`${minX - PAD} ${minY - PAD} ${maxX - minX + PAD * 2} ${maxY - minY + PAD * 2}`}
    >
      {idx.map((i) => {
        const [x, y, r, rx, ry] = layout[i];
        const k = keys?.[i] ?? {};
        const rot = r ? `rotate(${r / 100} ${rx} ${ry})` : undefined;
        if (k.rotary) {
          return (
            <g key={i} transform={rot}>
              <circle className="mk rot" cx={x + W / 2} cy={y + H / 2} r={W / 2 - 4} />
            </g>
          );
        }
        return (
          <g key={i} transform={rot}>
            <rect className={"mk" + (k.joy ? " joy" : "")}
                  x={x + 3} y={y + 3} width={W - 6} height={H - 6} rx={14} />
          </g>
        );
      })}
    </svg>
  );
}
