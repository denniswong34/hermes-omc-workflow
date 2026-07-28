const base = () => process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8787";

const PROJECT_HEADER = "X-OMC-Project-Id";

let activeProjectId: string | null = null;

export function setApiProjectId(projectId: string | null) {
  activeProjectId = projectId;
}

export function getApiProjectId(): string | null {
  return activeProjectId;
}

function projectHeaders(extra?: HeadersInit): HeadersInit {
  const headers: Record<string, string> = {};
  if (extra) {
    if (extra instanceof Headers) {
      extra.forEach((v, k) => {
        headers[k] = v;
      });
    } else if (Array.isArray(extra)) {
      for (const [k, v] of extra) headers[k] = v;
    } else {
      Object.assign(headers, extra);
    }
  }
  if (activeProjectId) {
    headers[PROJECT_HEADER] = activeProjectId;
  }
  return headers;
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    try {
      const j = JSON.parse(text) as { detail?: unknown };
      if (typeof j.detail === "string") {
        throw new Error(j.detail);
      }
      if (Array.isArray(j.detail)) {
        const msg = j.detail
          .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : JSON.stringify(d)))
          .join("; ");
        throw new Error(msg || `${res.status}`);
      }
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
    }
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    cache: "no-store",
    headers: projectHeaders(),
  });
  return parse<T>(res);
}

export async function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    method: "PUT",
    headers: projectHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  return parse<T>(res);
}

export async function apiPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    method: "POST",
    headers: projectHeaders(
      body === undefined ? undefined : { "Content-Type": "application/json" }
    ),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parse<T>(res);
}

export async function apiPatch<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    method: "PATCH",
    headers: projectHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  return parse<T>(res);
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    method: "DELETE",
    headers: projectHeaders(),
  });
  return parse<T>(res);
}
