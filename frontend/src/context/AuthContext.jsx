import { createContext, useCallback, useContext, useState } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [tenantId, setTenantId] = useState(null);

  const login = useCallback(async (credential) => {
    const res = await fetch("/api/auth-google", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Google login failed (${res.status})`);
    }
    const body = await res.json();
    setTenantId(body.tenant_id);
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/auth-logout", { method: "POST" });
    setTenantId(null);
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn: tenantId != null, tenantId, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
