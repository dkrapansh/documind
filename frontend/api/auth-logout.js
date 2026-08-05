import { USER_COOKIE_NAME } from "./auth-google.js";

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ detail: "Method not allowed" });
    return;
  }
  res.setHeader(
    "Set-Cookie",
    `${USER_COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`
  );
  res.status(204).end();
}
