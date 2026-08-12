export function StatusChip({ tone = "neutral", children }) {
  return <span className={`status-chip status-chip--${tone}`}>{children}</span>;
}
