import { useRef } from "react";
import { useScrollReveal } from "../hooks/useScrollReveal";
import { useCountUp } from "../hooks/useCountUp";
import "./Footer.css";

const STATS = [
  { value: 1.0, label: "Faithfulness" },
  { value: 0.83, label: "Answer relevancy" },
  { value: 0.79, label: "Context precision" },
];

function EvalStat({ value, label }) {
  const ref = useRef(null);
  useCountUp(ref, value, { decimals: 2 });
  return (
    <div className="ev">
      <div className="n" ref={ref}>
        0.0
      </div>
      <div className="l">{label}</div>
    </div>
  );
}

export function Footer() {
  const footerRef = useRef(null);
  useScrollReveal(footerRef);

  return (
    <footer ref={footerRef}>
      <div className="wrap">
        <div className="sec-eyebrow reveal">Measured, not eyeballed</div>
        <h2 className="foot-h reveal">
          Quality proven against a golden dataset, and re-run on every change.
        </h2>
        <div className="evrow reveal">
          {STATS.map((s) => (
            <EvalStat key={s.label} value={s.value} label={s.label} />
          ))}
        </div>
        <div className="foot-note mono">
          <span>FastAPI · Postgres + pgvector · Gemini · FlashRank ONNX · RAGAS</span>
          <span>documind-oyhv.onrender.com</span>
        </div>
      </div>
    </footer>
  );
}
