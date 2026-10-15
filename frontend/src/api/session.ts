/** The app is opened from an address with the access key of this run (`/?t=...`). It is handed to the server once, which turns it into an HttpOnly cookie; the address is
 *  then cleaned so the key does not stay in the history or in a bookmark. */
export async function bootstrapSession(): Promise<void> {
  const url = new URL(location.href);
  const t = url.searchParams.get("t");
  if (!t) return;
  try { await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: t }) }); } catch { /* the server is down: the app says so */ }
  url.searchParams.delete("t");
  history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
}
