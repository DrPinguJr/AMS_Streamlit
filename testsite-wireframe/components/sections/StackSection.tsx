import { WireBox, WireLines } from "@/components/wireframe/Primitives";

const CARDS = [
  { title: "Step one", note: "Sticks first, stays put while the rest arrive." },
  { title: "Step two", note: "Slides up and over the card before it." },
  { title: "Step three", note: "Each card's top offset is 14px further down." },
  { title: "Step four", note: "Last card ends on top of the pile." },
];

/**
 * 05 — Sticky card stack.
 *
 * No JS whatsoever: every card is `position: sticky` with a progressively
 * larger `top`, so they come to rest in a staggered pile as you scroll.
 * Each card needs an opaque background or the stack shows through.
 */
export function StackSection() {
  return (
    <div className="flex flex-col gap-8">
      {CARDS.map((card, i) => (
        <article
          key={card.title}
          className="sticky flex min-h-[58vh] flex-col justify-center rounded-lg p-8 sm:p-10"
          style={{
            // Offset each card below the sticky nav, then stagger the pile.
            top: `calc(var(--wf-nav-h) + ${i * 14}px)`,
            background: "var(--wf-panel)",
            border: "1px solid var(--wf-line-strong)",
          }}
        >
          <div className="grid items-center gap-8 md:grid-cols-2">
            <div>
              <span className="wf-chip">
                Card {i + 1} / {CARDS.length}
              </span>
              <h3 className="mt-5 text-2xl tracking-tight sm:text-3xl">
                {card.title}
              </h3>
              <p
                className="mt-3 max-w-sm text-[0.8rem] leading-relaxed"
                style={{ color: "var(--wf-muted)" }}
              >
                {card.note}
              </p>
              <div className="mt-6 max-w-sm">
                <WireLines count={2} />
              </div>
            </div>

            <WireBox
              label={`Card ${i + 1} media`}
              className="aspect-[3/2] w-full"
            />
          </div>
        </article>
      ))}
    </div>
  );
}
