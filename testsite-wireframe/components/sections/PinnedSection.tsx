"use client";

import { useRef, type CSSProperties } from "react";
import { useScrollProgress } from "@/hooks/useScrollProgress";
import { WireBox, WireLines } from "@/components/wireframe/Primitives";

const PANELS = 4;

const PANEL_CONTENT = [
  { title: "Panel one", note: "Enters already on screen when the pin engages." },
  { title: "Panel two", note: "Vertical scroll distance maps 1:1 to sideways travel." },
  { title: "Panel three", note: "Add or remove panels by changing one constant." },
  { title: "Panel four", note: "Last panel — the pin releases and the page continues." },
];

/**
 * 02 — Pinned / finite scroll.
 *
 * The outer wrapper is PANELS x 100vh tall. Inside it, a sticky full-height box
 * stays glued to the viewport while the wrapper scrolls past, and the panel
 * track slides sideways in step with progress. Once the wrapper is exhausted
 * the sticky box unsticks and the next section takes over.
 */
export function PinnedSection() {
  const ref = useRef<HTMLDivElement>(null);
  useScrollProgress(ref);

  return (
    <div
      ref={ref}
      style={
        {
          height: `${PANELS * 100}vh`,
          "--panels": PANELS,
        } as CSSProperties
      }
    >
      <div
        className="sticky top-0 h-screen overflow-hidden"
        style={{
          borderTop: "1px solid var(--wf-line)",
          borderBottom: "1px solid var(--wf-line)",
        }}
      >
        <div
          className="wf-track flex h-full"
          style={{ width: `${PANELS * 100}vw` }}
        >
          {PANEL_CONTENT.map((panel, i) => (
            <article
              key={panel.title}
              className="flex h-full w-screen shrink-0 flex-col justify-center px-6 pt-[var(--wf-nav-h)]"
              style={{
                borderRight:
                  i < PANELS - 1 ? "1px dashed var(--wf-line)" : undefined,
              }}
            >
              <div className="mx-auto grid w-full max-w-5xl items-center gap-10 md:grid-cols-2">
                <div>
                  <span className="wf-chip">
                    Panel {i + 1} / {PANELS}
                  </span>
                  <h3 className="mt-5 text-3xl tracking-tight sm:text-4xl">
                    {panel.title}
                  </h3>
                  <p
                    className="mt-3 max-w-sm text-[0.8rem] leading-relaxed"
                    style={{ color: "var(--wf-muted)" }}
                  >
                    {panel.note}
                  </p>
                  <div className="mt-6 max-w-sm">
                    <WireLines count={3} />
                  </div>
                </div>

                <WireBox
                  label={`Panel ${i + 1} media`}
                  className="aspect-[4/3] w-full"
                />
              </div>
            </article>
          ))}
        </div>

        {/* Progress rail — makes the scroll-to-travel mapping visible. */}
        <div
          className="absolute right-6 bottom-8 left-6 h-[2px]"
          style={{ background: "var(--wf-line)" }}
        >
          <div
            className="h-full"
            style={{
              width: "calc(var(--p, 0) * 100%)",
              background: "var(--wf-accent)",
            }}
          />
        </div>
      </div>
    </div>
  );
}
