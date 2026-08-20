export function StatusBanner({
  message,
  detail,
  tone = "info",
}: {
  message: string;
  detail?: string;
  tone?: "info" | "warning" | "danger";
}) {
  return (
    <aside className={`status-banner ${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <span className="status-banner-mark" aria-hidden="true">{tone === "info" ? "i" : "!"}</span>
      <div>
        <strong>{message}</strong>
        {detail && <p>{detail}</p>}
      </div>
    </aside>
  );
}
