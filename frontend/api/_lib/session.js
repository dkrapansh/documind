// Shared by every proxy function (documents.js, query-stream.js). The
// backend URL lives here as a plain (non-VITE_) env var, so it's only
// ever read server-side and never inlined into the client bundle.
const COOKIE_NAME = "dm_session";
// Set by api/auth-google.js on a real Google login - checked first so
// a logged-in visitor's own tenant takes priority over the anonymous
// demo one below, without documents.js/query-stream.js needing to
// know the difference.
const USER_COOKIE_NAME = "dm_user_session";
const BACKEND = process.env.DOCUMIND_API_BASE;
const SESSION_MAX_AGE_SECONDS = 3600;

// Same value as the backend's DEMO_PROXY_SHARED_SECRET. Lets the
// backend trust the X-Demo-Visitor-IP header set below instead of
// rate-limiting every visitor together under this proxy's own egress
// IP. See auth.py's _client_ip for the other half of this fix.
const PROXY_SHARED_SECRET = process.env.DOCUMIND_PROXY_SHARED_SECRET;

function parseCookie(cookieHeader, name) {
  if (!cookieHeader) return null;
  const pair = cookieHeader
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${name}=`));
  return pair ? decodeURIComponent(pair.slice(name.length + 1)) : null;
}

// Vercel's edge appends the IP it saw rather than replacing the header,
// so the LAST entry is the one it observed directly and can't be
// forged - unlike the FIRST entry, which is whatever the client sent
// and used to be trusted here, letting a caller dodge the IP limit.
function _visitorIp(req) {
  const xff = req.headers["x-forwarded-for"];
  if (xff) {
    const hops = xff.split(",").map((s) => s.trim()).filter(Boolean);
    if (hops.length) return hops[hops.length - 1];
  }
  return req.socket?.remoteAddress ?? "unknown";
}

/**
 * Returns the caller's API key: a real logged-in user's key if
 * dm_user_session is set (see auth-google.js), otherwise the
 * anonymous visitor's demo key, minting a fresh ephemeral tenant via
 * POST /auth/demo-session if this browser doesn't have one yet either.
 * The raw key never reaches the browser as JS-readable state - only
 * as the value of an httpOnly cookie set on the response.
 */
export async function getSessionKey(req) {
  const userKey = parseCookie(req.headers.cookie, USER_COOKIE_NAME);
  if (userKey) return { key: userKey, isNew: false };

  const existing = parseCookie(req.headers.cookie, COOKIE_NAME);
  if (existing) return { key: existing, isNew: false };

  const headers = {};
  if (PROXY_SHARED_SECRET) {
    headers["X-Demo-Proxy-Secret"] = PROXY_SHARED_SECRET;
    headers["X-Demo-Visitor-IP"] = _visitorIp(req);
  }

  const res = await fetch(`${BACKEND}/auth/demo-session`, { method: "POST", headers });
  if (!res.ok) {
    // Carries the backend's real status and message (rate limited,
    // demo at capacity, etc.) instead of a flat 502, so the browser can
    // show the visitor something true instead of "couldn't reach the demo".
    const body = await res.json().catch(() => ({}));
    const error = new Error(body.detail || `Failed to mint demo session (${res.status})`);
    error.status = res.status;
    throw error;
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
