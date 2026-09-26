/** Success rate against the Phase 1 target (≥ 80%). */
export function RateBadge({ rate, target }: { rate: number | null; target: number }) {
  if (rate === null) return <span className="text-sm text-muted">—</span>;
  const ok = rate >= target;
  return (
    <span
      className={`rounded-full border px-3 py-1 text-sm font-semibold ${ok ? "border-success text-success" : "border-danger text-danger"}`}
    >
      {Math.round(rate * 100)}% / {Math.round(target * 100)}%
    </span>
  );
}
