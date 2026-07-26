import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.jsx";

if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.documentElement.classList.add("no-motion");
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
