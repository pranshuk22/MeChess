export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** JSON request to the backend; errors carry the server's own plain-language message when it sent one. */
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, { ...rest, headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers }, body: json !== undefined ? JSON.stringify(json) : rest.body });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const d = await res.json(); if (typeof d.detail === "string") msg = d.detail; else if (Array.isArray(d.detail)) msg = d.detail.map((x: { msg: string }) => x.msg).join("; "); } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
