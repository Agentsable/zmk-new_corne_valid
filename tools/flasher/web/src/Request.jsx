export function fmt(at) {
  return at ? new Date(at * 1000).toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

/** The request card, same shape the firmware-update page shows. */
export default function RequestCard({ at, description, label = "Update requested" }) {
  return (
    <div className="request static">
      <span className="req-when">{label} {fmt(at)}</span>
      <span className="req-desc">{description}</span>
    </div>
  );
}
