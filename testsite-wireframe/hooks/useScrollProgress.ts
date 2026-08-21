"use client";

import { useEffect, type RefObject } from "react";

/**
 * Writes the element's scroll progress (0 -> 1) into a CSS custom property on
 * that same element, updated inside requestAnimationFrame.
 *
 * Progress is measured across the element's "pinned range": the distance it can
 * travel while a sticky child stays glued to the viewport, i.e.
 * `element.height - viewport.height`.
 *
 * Deliberately does NOT use React state. Children read the value through
 * `var(--p)` in CSS, so scrolling never triggers a re-render.
 */
export function useScrollProgress<T extends HTMLElement>(
  ref: RefObject<T | null>,
  varName = "--p",
) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let frame = 0;

    const update = () => {
      frame = 0;
      const rect = el.getBoundingClientRect();
      const range = rect.height - window.innerHeight;
      // A section shorter than the viewport has no pinned range to scrub.
      const progress = range <= 0 ? 0 : -rect.top / range;
      const clamped = Math.min(1, Math.max(0, progress));
      el.style.setProperty(varName, clamped.toFixed(4));
    };

    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);

    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref, varName]);
}
