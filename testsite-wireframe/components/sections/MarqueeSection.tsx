import type { CSSProperties } from "react";
import { WireBox } from "@/components/wireframe/Primitives";

type Item = { type: "image" | "text"; label: string };

const ROW_ONE: Item[] = [
  { type: "image", label: "Image A" },
  { type: "text", label: "Floating text snippet" },
  { type: "image", label: "Image B" },
  { type: "text", label: "Another line of copy" },
  { type: "image", label: "Image C" },
  { type: "text", label: "Short caption" },
];

const ROW_TWO: Item[] = [
  { type: "text", label: "Reverse direction" },
  { type: "image", label: "Image D" },
  { type: "text", label: "Mixed media strip" },
  { type: "image", label: "Image E" },
  { type: "text", label: "Hover to pause" },
  { type: "image", label: "Image F" },
];

/**
 * 04 — Infinite floating marquee.
 *
 * Two rows, opposite directions, pure CSS. Each row renders its items twice so
 * the -50% translate lands on an identical frame and the seam is invisible.
 */
export function MarqueeSection() {
  return (
    <div className="flex flex-col gap-6 py-4">
      <MarqueeRow items={ROW_ONE} speed="48s" />
      <MarqueeRow items={ROW_TWO} speed="62s" direction="reverse" />
    </div>
  );
}

function MarqueeRow({
  items,
  speed,
  direction,
}: {
  items: Item[];
  speed: string;
  direction?: "reverse";
}) {
  // Rendered twice: one visible cycle plus its identical continuation.
  const loop = [...items, ...items];

  return (
    <div className="wf-marquee overflow-hidden py-4">
      {/* Spacing lives on the items, not as a track `gap`: a gap adds an extra
          half-space between the two copies, which knocks -50% off the seam. */}
      <div
        className="wf-marquee-track"
        data-direction={direction}
        style={{ "--speed": speed } as CSSProperties}
      >
        {loop.map((item, i) => (
          <div
            key={i}
            className="wf-bob mr-5 shrink-0"
            style={
              {
                // Stagger the bob so the row never pulses in unison.
                "--delay": `${(i % items.length) * 0.4}s`,
                "--bob": `${3 + (i % 3) * 0.6}s`,
              } as CSSProperties
            }
            // The duplicated half is decorative; keep it out of the a11y tree.
            aria-hidden={i >= items.length}
          >
            {item.type === "image" ? (
              <WireBox label={item.label} className="h-32 w-52 sm:h-36 sm:w-60" />
            ) : (
              <div
                className="flex h-32 w-52 items-center justify-center rounded-md px-5 text-center text-sm sm:h-36 sm:w-60"
                style={{
                  border: "1px dashed var(--wf-line-strong)",
                  background: "var(--wf-panel)",
                  color: "var(--wf-muted)",
                }}
              >
                {item.label}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
