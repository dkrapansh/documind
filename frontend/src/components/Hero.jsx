import { useLayoutEffect, useRef, useState } from "react";
import { gsap, prefersReducedMotion } from "../lib/gsapSetup";
import "./Hero.css";

function splitToChars(text, keyPrefix) {
  return text.split(/(\s+)/).map((part, i) => {
    if (part === "") return null;
    if (/^\s+$/.test(part)) return part;
    return (
      <span className="word" key={`${keyPrefix}-${i}`}>
        {[...part].map((ch, j) => (
          <span className="char" key={j}>
            {ch}
          </span>
        ))}
      </span>
    );
  });
}

const TRACE_SOURCES = [
  {
    id: "c1",
    label: "handbook · chunk 18",
    score: "0.88",
    text: "…full-time staff accrue vacation at 1.25 days per month, totaling 15 days annually in year one…",
  },
  {
    id: "c2",
    label: "handbook · chunk 19",
    score: "0.81",
    text: "…after three years of continuous service the annual allotment increases to 20 days…",
  },
];

export function Hero() {
  const headerRef = useRef(null);
  const hlRef = useRef(null);
  const [activeSource, setActiveSource] = useState(null);

  useLayoutEffect(() => {
    const root = headerRef.current;
    if (!root) return;

    if (prefersReducedMotion()) {
      root.querySelectorAll(".reveal").forEach((n) => {
        n.style.opacity = 1;
        n.style.transform = "none";
      });
      hlRef.current?.classList.add("draw");
      return;
    }

    const ctx = gsap.context(() => {
      gsap.to(root.querySelectorAll("h1 .char"), {
        y: 0,
        duration: 0.9,
        ease: "power4.out",
        stagger: 0.012,
        delay: 0.2,
      });
      gsap.to(root.querySelectorAll(".reveal"), {
        opacity: 1,
        y: 0,
        duration: 0.9,
        ease: "power3.out",
        stagger: 0.09,
        delay: 0.7,
      });
      gsap.delayedCall(0.9, () => hlRef.current?.classList.add("draw"));
    }, root);

    return () => ctx.revert();
  }, []);

  const scrollToDemo = () => document.getElementById("demo")?.scrollIntoView({ behavior: "smooth" });

  return (
    <header ref={headerRef}>
      <div className="wrap">
        <div className="eyebrow reveal">Multi-tenant document Q&amp;A</div>
        <h1>
          {splitToChars("Every answer ", "a")}
          <span className="hl" ref={hlRef}>
            {splitToChars("traces back", "b")}
          </span>
          {splitToChars(" to the page it came from.", "c")}
        </h1>
        <p className="sub reveal">
          Upload a document, ask in plain language, and read an answer grounded in the source,
          with the exact chunks it used, and an honest refusal when the answer isn&apos;t there.
        </p>
        <div className="cta-row reveal">
          <button className="btn" onClick={scrollToDemo}>
            Try it live
          </button>
          <a className="btn ghost" href="https://github.com/dkrapansh/documind" target="_blank" rel="noreferrer">
            Read the design →
          </a>
        </div>

        <div className="trace-card reveal">
          <div className="trace-answer">
            <div className="tlabel mono">Answer</div>
            <div className="answer-txt">
              New full-time employees accrue{" "}
              <span
                className="cited"
                data-active={activeSource === "c1"}
                onMouseEnter={() => setActiveSource("c1")}
                onMouseLeave={() => setActiveSource(null)}
              >
                15 paid vacation days
              </span>{" "}
              in their first year, rising to{" "}
              <span
                className="cited"
                data-active={activeSource === "c2"}
                onMouseEnter={() => setActiveSource("c2")}
                onMouseLeave={() => setActiveSource(null)}
              >
                20 days after three years
              </span>{" "}
              of continuous service.
            </div>
          </div>
          <div className="trace-sources">
            <div className="tlabel mono">Cited sources</div>
            {TRACE_SOURCES.map((s) => (
              <div
                className="chunk"
                key={s.id}
                data-active={activeSource === s.id}
                onMouseEnter={() => setActiveSource(s.id)}
                onMouseLeave={() => setActiveSource(null)}
              >
                <div className="chunk-head">
                  <span className="chunk-id mono">{s.label}</span>
                  <span className="chunk-score mono">{s.score}</span>
                </div>
                <div className="chunk-txt">{s.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}
