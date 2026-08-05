import { BACKEND } from "./_lib/session.js";

const USER_COOKIE_NAME = "dm_user_session";
// A real login, not an ephemeral demo tenant - long-lived rather than
// the demo's 1-hour TTL. The backend itself has no expiry on the key;
// this is just how long the browser holds onto it before a re-login
// is required. Signing in again anytime issues a fresh one anyway.
const USER_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

/**
 * Takes the Google ID token from the frontend's Sign-in-with-Google
 * button, verifies it via the backend's POST /auth/google, and holds
 * the resulting API key in its own httpOnly cookie - separate from
 * the anonymous demo session's dm_session cookie, so a real login and
 * an anonymous demo visit never collide in the same browser.
 */
export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ detail: "Method not allowed" });
    return;
  }

  // Unlike documents.js's multipart upload body, Vercel's Node.js
  // runtime auto-parses a JSON request body into req.body before this
  // handler runs, consuming the raw stream in the process - reading
  // req directly here (as documents.js does) would see an empty
  // stream.
  const credential = req.body?.credential;
  if (!credential) {
    res.status(400).json({ detail: "Missing credential" });
    return;
  }

  const upstream = await fetch(`${BACKEND}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: credential }),
  });
  const body = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    res.status(upstream.status).json(body);
    return;
  }

  res.setHeader(
    "Set-Cookie",
    `${USER_COOKIE_NAME}=${encodeURIComponent(body.api_key)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${USER_SESSION_MAX_AGE_SECONDS}`
  );
  res.status(200).json({ tenant_id: body.tenant_id });
}

export { USER_COOKIE_NAME };
