import { useLayoutEffect, useRef } from "react";
import { gsap, prefersReducedMotion } from "../lib/gsapSetup";
import { useScrollReveal } from "../hooks/useScrollReveal";
import "./Refusal.css";

function GaugeBar({ width, low }) {
  const fillRef = useRef(null);

  useLayoutEffect(() => {
    const el = fillRef.current;
    if (!el) return;

    if (prefersReducedMotion()) {
      el.style.width = `${width}%`;
      return;
    }

    const ctx = gsap.context(() => {
      gsap.to(el, {
        width: `${width}%`,
        duration: 1.1,
        ease: "power2.out",
        scrollTrigger: { trigger: el, start: "top 88%" },
      });
    });
    return () => ctx.revert();
  }, [width]);

  return (
    <div className="bar">
      <div className={`bar-fill${low ? " low" : ""}`} ref={fillRef} />
      <div className="thresh" />
    </div>
  );
}

export function Refusal() {
  const sectionRef = useRef(null);
  useScrollReveal(sectionRef);

  return (
    <section className="refuse" ref={sectionRef}>
      <div className="wrap">
        <div className="sec-eyebrow reveal">The part most RAG demos skip</div>
        <h2 className="sec-h reveal">It refuses to guess.</h2>
        <div className="two-col">
          <p className="sec-body reveal">
            The confidence check happens <b>before</b> the model is ever called. If the best
            reranked chunk scores below <b>0.70</b>, DocuMind answers{" "}
            <b>&ldquo;I can&apos;t answer that confidently.&rdquo;</b> A refusal costs nothing
            beyond the retrieval that already ran.
          </p>
          <div className="gauge reveal">
            <div className="gauge-title">Answerable query</div>
            <GaugeBar width={88} />
            <div className="gauge-cap">
              <span className="verdict ok mono">0.88 ≥ 0.70 · answered</span>
            </div>
            <div className="gauge-title" style={{ marginTop: 26 }}>
              Out-of-scope query
            </div>
            <GaugeBar width={41} low />
            <div className="gauge-cap">
              <span className="verdict no mono">0.41 &lt; 0.70 · refused, no model call</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
