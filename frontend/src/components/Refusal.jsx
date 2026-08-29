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
            The model answers <b>only</b> from the retrieved chunks, and replies with a fixed
            refusal sentence when they do not contain the answer. Refusing is a decision made
            after reading the text, not a score compared against a cutoff.
          </p>
          {/* The widths are illustrative of two outcomes, not scores. They used to be
              88 and 41, which bracketed the retired 0.70 gate's measured separation,
              so this section argued against score-based refusal while drawing one. */}
          <div className="gauge reveal">
            <div className="gauge-title">In the documents</div>
            <GaugeBar width={92} />
            <div className="gauge-cap">
              <span className="verdict ok mono">answered, with sources cited</span>
            </div>
            <div className="gauge-title" style={{ marginTop: 26 }}>
              Not in the documents
            </div>
            <GaugeBar width={22} low />
            <div className="gauge-cap">
              <span className="verdict no mono">refused, no sources shown</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
