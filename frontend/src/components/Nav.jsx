import { useEffect, useRef } from "react";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/AuthContext";
import "./Nav.css";

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

function GoogleSignInButton() {
  const { theme } = useTheme();
  const { login } = useAuth();
  const buttonRef = useRef(null);

  useEffect(() => {
    if (!CLIENT_ID) return;

    let cancelled = false;
    const tryInit = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) {
        setTimeout(tryInit, 100);
        return;
      }
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: (response) => {
          login(response.credential).catch((err) => {
            console.error("Google login failed:", err);
          });
        },
      });
      if (buttonRef.current) {
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: theme === "dark" ? "filled_black" : "outline",
          size: "medium",
          type: "standard",
        });
      }
    };
    tryInit();
    return () => {
      cancelled = true;
    };
  }, [theme, login]);

  if (!CLIENT_ID) return null;
  return <div className="gsi-slot" ref={buttonRef} />;
}

export function Nav() {
  const { theme, toggleTheme } = useTheme();
  const { isLoggedIn, logout } = useAuth();

  const scrollToDemo = (e) => {
    e.preventDefault();
    document.getElementById("demo")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <nav>
      <a className="brand" href="#top" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
        Docu<span>Mind</span>
      </a>
      <div className="nav-right">
        {/* No version here on purpose. This was the one version string in the
            project not derived from APP_VERSION, and it drifted to v1.0 while the
            service reported 0.1.0. The live version is served by /health/live. */}
        <div className="navmeta mono">RAG API · live</div>
        <a className="navmeta mono nav-demo-link" href="#demo" onClick={scrollToDemo}>
          demo
        </a>
        {isLoggedIn ? (
          <button className="theme-toggle" onClick={logout}>
            Sign out
          </button>
        ) : (
          <GoogleSignInButton />
        )}
        <button
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label="Switch color theme"
        >
          <span className="ic" aria-hidden="true" />
          <span>{theme === "dark" ? "Light" : "Dark"}</span>
        </button>
      </div>
    </nav>
  );
}
