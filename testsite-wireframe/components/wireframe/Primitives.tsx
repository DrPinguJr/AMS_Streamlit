import type { CSSProperties, ReactNode } from "react";

/**
 * Placeholder media block — grey fill with the classic diagonal cross.
 * Swap these for `next/image` when real assets exist.
 */
export function WireBox({
  label,
  className = "",
  style,
}: {
  label?: string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={`wf-box rounded-md ${className}`} style={style}>
      {label ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center">
          <span
            className="px-2 py-1 text-[0.6rem] uppercase tracking-[0.14em]"
            style={{
              background: "var(--wf-panel)",
              color: "var(--wf-muted)",
              border: "1px solid var(--wf-line)",
              borderRadius: 4,
            }}
          >
            {label}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Grey bars standing in for a paragraph of copy. */
export function WireLines({
  count = 3,
  className = "",
}: {
  count?: number;
  className?: string;
}) {
  // Last bar runs short so the block reads as real prose, not a solid slab.
  const widths = ["100%", "94%", "97%", "88%", "92%"];

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="wf-line"
          style={{
            width: i === count - 1 ? "62%" : widths[i % widths.length],
          }}
        />
      ))}
    </div>
  );
}

/** Placeholder CTA. `variant="solid"` marks the primary action. */
export function WireButton({
  children,
  variant = "outline",
}: {
  children: ReactNode;
  variant?: "solid" | "outline";
}) {
  const solid = variant === "solid";

  return (
    <span
      className="inline-flex items-center justify-center rounded-md px-5 py-2.5 text-xs uppercase tracking-[0.14em]"
      style={{
        background: solid ? "var(--wf-accent)" : "transparent",
        color: solid ? "var(--wf-bg)" : "var(--wf-ink)",
        border: `1px solid ${solid ? "var(--wf-accent)" : "var(--wf-line-strong)"}`,
      }}
    >
      {children}
    </span>
  );
}

/** Heading stand-in: a couple of chunky bars at headline weight. */
export function WireHeading({ className = "" }: { className?: string }) {
  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div
        className="wf-line"
        style={{ height: "1.75rem", width: "88%", background: "var(--wf-line)" }}
      />
      <div
        className="wf-line"
        style={{ height: "1.75rem", width: "56%", background: "var(--wf-line)" }}
      />
    </div>
  );
}
