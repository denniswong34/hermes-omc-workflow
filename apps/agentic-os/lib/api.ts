export async function apiGet<T = unknown>(path: string): Promise<T> {
  const base = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8787";
  const res = await fetch(`${base}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  const base = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8787";
  const res = await fetch(`${base}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}
