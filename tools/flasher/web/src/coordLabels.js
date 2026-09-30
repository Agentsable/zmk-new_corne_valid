/** Name every key as half + matrix row + column within that half.
 *
 * Shared by the coordinates page and the keymap views so the two can never
 * drift into naming the same key differently.
 *
 * The joystick and rotary are named, not numbered. They share matrix rows with
 * ordinary keys, so counting them as columns makes the right half start at
 * R0-1 and sorts joystick-right ahead of the right thumbs.
 */
const JOY = { up: "JOY↑", down: "JOY↓", left: "JOY←", right: "JOY→", centre: "JOY•" };

export function coordLabels(layout, rc, keys) {
  if (!layout?.length || !rc?.length) return [];
  // keys carries the joystick/rotary flags, and those five keys are NAMED
  // rather than numbered. Without them every remaining key shifts into their
  // column slots and 27 of the 48 labels silently change meaning -- R10 stops
  // being "H" and becomes the joystick's down key. A caller with no keys is
  // asking for labels that cannot be computed, so give it none rather than
  // wrong ones. /api/keymap returning layers: [] is the live path here.
  if (!keys?.length || keys.length !== layout.length) return [];
  const xs = layout.map((p) => p[0]);
  const split = (Math.min(...xs) + Math.max(...xs)) / 2;
  const half = (i) => (layout[i][0] < split ? "L" : "R");

  const special = (i) => {
    const k = keys?.[i] ?? {};
    if (k.rotary) return "ROT";
    if (k.joy) return JOY[k.joy] ?? "JOY";
    return null;
  };

  const buckets = {};
  layout.forEach((_, i) => {
    if (special(i)) return;
    (buckets[`${half(i)}${rc[i][0]}`] ??= []).push(i);
  });
  const col = {};
  Object.values(buckets).forEach((list) => {
    list.sort((a, b) => layout[a][0] - layout[b][0]);
    list.forEach((i, n) => { col[i] = n; });
  });

  return layout.map((_, i) => {
    const sp = special(i);
    return { label: sp ?? `${half(i)}${rc[i][0]}${col[i]}`, special: Boolean(sp) };
  });
}
