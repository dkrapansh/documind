import { useLayoutEffect } from "react";
import { gsap, ScrollTrigger, prefersReducedMotion } from "../lib/gsapSetup";

/**
 * Counts a number element from 0 to `end` when it scrolls into view.
 * `decimals` controls fixed-point formatting (e.g. 2 for "0.88").
 */
export function useCountUp(ref, end, { decimals = 0, start = "top 90%", duration = 1.3 } = {}) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (prefersReducedMotion()) {
      el.textContent = decimals ? end.toFixed(decimals) : String(Math.round(end));
      return;
    }

    const obj = { v: 0 };
    const ctx = gsap.context(() => {
      gsap.to(obj, {
        v: end,
        duration,
        ease: "power2.out",
        scrollTrigger: { trigger: el, start },
        onUpdate() {
          el.textContent = decimals ? obj.v.toFixed(decimals) : String(Math.round(obj.v));
        },
      });
    });

    return () => ctx.revert();
  }, [ref, end, decimals, start, duration]);
}
