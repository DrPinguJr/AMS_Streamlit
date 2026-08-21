"use client";

import { useRef, type CSSProperties } from "react";
import { useScrollProgress } from "@/hooks/useScrollProgress";
import { WireBox } from "@/components/wireframe/Primitives";

/**
 * Where each tile sits at progress 0. All offsets interpolate to zero, so at
 * progress 1 the tiles land in their natural grid position.
 */
const TILES = [
  { dx: "-26vw", dy: "-16vh", r: "-14deg" },
  { dx: "0vw", dy: "-24vh", r: "10deg" },
  { dx: "26vw", dy: "-18vh", r: "16deg" },
  { dx: "-28vw", dy: "18vh", r: "12deg" },
  { dx: "2vw", dy: "26vh", r: "-12deg" },
  { dx: "27vw", dy: "16vh", r: "-16deg" },
];

/**
 * 03 — Images converge on scroll.
 *
 * Identical pin mechanic to section 02, but progress drives per-tile transforms
 * instead of a horizontal track. JS writes one number (`--p`); CSS does the rest.
 */
export function ConvergeSection() {
  const ref = useRef<HTMLDivElement>(null);
  useScrollProgress(ref);

  return (
    <div ref={ref} style={{ height: "250vh" }}>
      <div
        className="wf-grid-bg sticky top-0 flex h-screen items-center overflow-hidden"
        style={{
          borderTop: "1px solid var(--wf-line)",
          borderBottom: "1px solid var(--wf-line)",
        }}
      >
        <div className="mx-auto w-full max-w-4xl px-6 pt-[var(--wf-nav-h)]">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 sm:gap-5">
            {TILES.map((tile, i) => (
              <WireBox
                key={i}
                label={`Image ${i + 1}`}
                className="wf-converge aspect-[4/3] w-full"
                style={
                  {
                    "--dx": tile.dx,
                    "--dy": tile.dy,
                    "--r": tile.r,
                  } as CSSProperties
                }
              />
            ))}
          </div>

        </div>

        {/* Pulled out of the grid's flow so drifting tiles never overlap it,
            and faded out once they have landed. */}
        <p
          className="pointer-events-none absolute right-0 bottom-8 left-0 text-center text-[0.7rem] uppercase tracking-[0.16em]"
          style={{
            color: "var(--wf-muted)",
            opacity: "calc(1 - var(--p, 0))",
          }}
        >
          Keep scrolling — the tiles settle into the grid
        </p>
      </div>
    </div>
  );
}
