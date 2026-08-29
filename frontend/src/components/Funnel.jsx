import { useLayoutEffect, useRef } from "react";
import { gsap, ScrollTrigger, prefersReducedMotion } from "../lib/gsapSetup";
import { useScrollReveal } from "../hooks/useScrollReveal";
import { useCountUp } from "../hooks/useCountUp";
import "./Funnel.css";

const STAGES = [
  { key: "01 · retrieve", count: 20, desc: "dense (pgvector) + BM25, top 10 each", dots: 20 },
  { key: "02 · fuse", count: 14, desc: "Reciprocal Rank Fusion, by position", dots: 14 },
  { key: "03 · rerank", count: 4, desc: "cross-encoder reads query + chunk together", dots: 4 },
  { key: "04 · judge", count: null, desc: "model reads the context: answer, or refuse", dots: 1, staticValue: "LLM" },
];

export function Funnel() {
  const sectionRef = useRef(null);
  const funnelRef = useRef(null);
  useScrollReveal(sectionRef);

  useLayoutEffect(() => {
    const funnelEl = funnelRef.current;
    if (!funnelEl) return;

    const stageEls = funnelEl.querySelectorAll(".fstage");

    if (prefersReducedMotion()) {
      stageEls.forEach((st) => {
        st.classList.add("lit");
        const num = st.querySelector("[data-count]");
        if (num) num.textContent = num.dataset.count;
      });
      return;
    }

    const ctx = gsap.context(() => {
      ScrollTrigger.create({
        trigger: funnelEl,
        start: "top 68%",
        once: true,
        onEnter() {
          stageEls.forEach((st, i) => {
            gsap.delayedCall(i * 0.32, () => {
              st.classList.add("lit");
              const num = st.querySelector("[data-count]");
              if (num) {
                const end = Number(num.dataset.count);
                const o = { v: 0 };
                gsap.to(o, {
                  v: end,
                  duration: 0.7,
                  ease: "power2.out",
                  onUpdate() {
                    num.textContent = String(Math.round(o.v));
                  },
                });
              }
            });
          });
        },
      });
    }, funnelEl);

    return () => ctx.revert();
  }, []);

  return (
    <section className="funnel-sec" ref={sectionRef}>
      <div className="wrap">
        <div className="sec-eyebrow reveal">Cheap and wide, then expensive and narrow</div>
        <h2 className="sec-h reveal">Twenty candidates in. Four make it out.</h2>
        <p className="sec-body reveal" style={{ marginTop: 24 }}>
          Every query fans out across two retrievers, gets fused by position, then reranked down
          to the handful of chunks that actually earn a place in the prompt.
        </p>

        <div className="funnel" ref={funnelRef}>
          {STAGES.map((stage, i) => (
            <div className="fstage" data-i={i} key={stage.key}>
              <div className="fk">{stage.key}</div>
              <div className="dots">
                {Array.from({ length: stage.dots }).map((_, j) => (
                  <span className="fdot" key={j} />
                ))}
              </div>
              <div>
                <div className="fn" data-count={stage.count ?? undefined}>
                  {stage.staticValue ?? 0}
                </div>
                <div className="fd">{stage.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="band">
          <div className="band-in">
            <BandStat value={555} end2={120} cap="The reranker was rewritten from PyTorch to ONNX after it OOM'd on a 512MB host: same model class, one-fifth the memory." />
            <BandStatSimple value={8} of={8} cap="All 8 unanswerable questions in the golden dataset are refused. The model reads the retrieved context and says so, rather than a score threshold guessing from similarity alone." />
          </div>
        </div>
      </div>
    </section>
  );
}

function BandStat({ value, end2, cap }) {
  const ref1 = useRef(null);
  const ref2 = useRef(null);
  useCountUp(ref1, value);
  useCountUp(ref2, end2);
  return (
    <div className="stat reveal">
      <div className="big">
        <span className="sp" ref={ref1}>
          0
        </span>
        MB → <span ref={ref2}>0</span>MB
      </div>
      <div className="cap">{cap}</div>
    </div>
  );
}

function BandStatSimple({ value, of, cap }) {
  const ref1 = useRef(null);
  useCountUp(ref1, value);
  return (
    <div className="stat reveal">
      <div className="big">
        <span className="sp" ref={ref1}>
          0
        </span>{" "}
        / {of}
      </div>
      <div className="cap">{cap}</div>
    </div>
  );
}
