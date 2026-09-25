// Phase 0 placeholder: proves web → api → postgres/redis wiring end to end.
export const dynamic = "force-dynamic";

type Ready = { status: string; checks: Record<string, string> };

async function getApiStatus(): Promise<Ready | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://api:8000";
  try {
    const res = await fetch(`${base}/ready`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    return (await res.json()) as Ready;
  } catch {
    return null;
  }
}

export default async function Home() {
  const status = await getApiStatus();
  const rows: [string, string][] = status
    ? [["api", "ok"], ...Object.entries(status.checks)]
    : [["api", "unreachable"]];

  return (
    <main style={{ maxWidth: 480, margin: "0 auto", padding: "80px 16px" }}>
      <h1 style={{ fontSize: 28, margin: 0 }}>
        DEL SOCIAL <span style={{ color: "var(--accent)" }}>AI</span>
      </h1>
      <p style={{ opacity: 0.7, marginTop: 8 }}>Phase 0 — system status</p>
      <ul style={{ listStyle: "none", padding: 0, marginTop: 24 }}>
        {rows.map(([name, value]) => (
          <li
            key={name}
            style={{
              display: "flex",
              justifyContent: "space-between",
              background: "var(--surface)",
              padding: "12px 16px",
              borderRadius: 8,
              marginBottom: 8,
            }}
          >
            <span>{name}</span>
            <span>{value === "ok" ? "✅ ok" : `❌ ${value}`}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
