import { useTheme } from "../context/ThemeContext";
import "./Nav.css";

export function Nav() {
  const { theme, toggleTheme } = useTheme();

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
        <div className="navmeta mono">RAG API · v1.0 · live</div>
        <a className="navmeta mono nav-demo-link" href="#demo" onClick={scrollToDemo}>
          demo
        </a>
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
