import { useLayoutEffect } from "react";
import { gsap, ScrollTrigger, prefersReducedMotion } from "../lib/gsapSetup";

/**
 * Fades up every `.reveal` element inside containerRef as it scrolls into
 * view. Matches the mockup's quiet register: 18px rise, power3.out, 0.85s,
 * staggered, trigger at "top 86%".
 */
export function useScrollReveal(containerRef, { stagger = 0.09, delay = 0 } = {}) {
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    if (prefersReducedMotion()) {
      el.querySelectorAll(".reveal").forEach((n) => {
        n.style.opacity = 1;
        n.style.transform = "none";
      });
      return;
    }

    const targets = el.querySelectorAll(".reveal");
    if (!targets.length) return;

    const ctx = gsap.context(() => {
      gsap.to(targets, {
        opacity: 1,
        y: 0,
        duration: 0.85,
        ease: "power3.out",
        stagger,
        delay,
        scrollTrigger: {
          trigger: el,
          start: "top 86%",
        },
      });
    }, el);

    return () => ctx.revert();
  }, [containerRef, stagger, delay]);
}
