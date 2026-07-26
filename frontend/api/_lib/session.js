// Shared by every proxy function (documents.js, query-stream.js). The
// backend URL lives here as a plain (non-VITE_) env var, so it's only
// ever read server-side and never inlined into the client bundle.
const COOKIE_NAME = "dm_session";
const BACKEND = process.env.DOCUMIND_API_BASE;
const SESSION_MAX_AGE_SECONDS = 3600;

function parseCookie(cookieHeader, name) {
  if (!cookieHeader) return null;
  const pair = cookieHeader
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${name}=`));
  return pair ? decodeURIComponent(pair.slice(name.length + 1)) : null;
}

/**
 * Returns the visitor's demo API key, minting a fresh ephemeral tenant
 * via POST /auth/demo-session on the backend if this browser doesn't
 * have one yet. The raw key never reaches the browser as JS-readable
 * state - only as the value of an httpOnly cookie set on the response.
 */
export async function getSessionKey(req) {
  const existing = parseCookie(req.headers.cookie, COOKIE_NAME);
  if (existing) return { key: existing, isNew: false };

  const res = await fetch(`${BACKEND}/auth/demo-session`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Failed to mint demo session (${res.status})`);
  }
  const body = await res.json();
  return { key: body.api_key, isNew: true };
}

export function attachSessionCookie(res, key) {
  res.setHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=${encodeURIComponent(key)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_MAX_AGE_SECONDS}`
  );
}

export { BACKEND };
