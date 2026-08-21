import { WireBox, WireLines } from "@/components/wireframe/Primitives";

const CARD_COUNT = 6;

/**
 * 06 — Content grid.
 *
 * The baseline case. `auto-fit` + `minmax` means it reflows from 3 columns to 1
 * without a single media query, and it proves the section shell works fine with
 * no scroll effect attached.
 */
export function GridSection() {
  return (
    <div
      className="grid gap-5"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}
    >
      {Array.from({ length: CARD_COUNT }).map((_, i) => (
        <article
          key={i}
          className="rounded-lg p-5"
          style={{
            background: "var(--wf-panel)",
            border: "1px solid var(--wf-line)",
          }}
        >
          <WireBox label={`Card ${i + 1}`} className="aspect-[16/10] w-full" />

          <div
            className="mt-4 text-[0.6rem] uppercase tracking-[0.16em]"
            style={{ color: "var(--wf-accent)" }}
          >
            Category
          </div>

          <div
            className="wf-line mt-2"
            style={{ height: "1rem", width: "72%", background: "var(--wf-line)" }}
          />

          <div className="mt-4">
            <WireLines count={3} />
          </div>
        </article>
      ))}
    </div>
  );
}
