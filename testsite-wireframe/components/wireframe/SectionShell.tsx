import type { ReactNode } from "react";
import type { SectionMeta } from "@/lib/sections";

/**
 * Wraps every section with its anchor, its numbered chip, and the two
 * annotation notes that explain what the section is for and how it is built.
 *
 * This is the "wireframe" layer. When the site becomes a real design, delete
 * the <header> block and the shell collapses to a plain <section>.
 */
export function SectionShell({
  meta,
  children,
  bleed = false,
}: {
  meta: SectionMeta;
  children: ReactNode;
  /** Full-bleed sections (pinned, marquee) manage their own width. */
  bleed?: boolean;
}) {
  return (
    <section
      id={meta.id}
      style={{ borderTop: "1px solid var(--wf-line)" }}
      className="scroll-mt-14"
    >
      <header className="mx-auto w-full max-w-6xl px-6 pt-16 pb-10">
        <div className="flex flex-wrap items-center gap-4">
          <span className="wf-chip">
            {meta.index} <span aria-hidden>/</span> {meta.navLabel}
          </span>
          <h2 className="text-xl tracking-tight sm:text-2xl">{meta.title}</h2>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <Note title="What it's for" body={meta.purpose} />
          <Note title="How it works" body={meta.mechanic} accent />
        </div>
      </header>

      {bleed ? (
        children
      ) : (
        <div className="mx-auto w-full max-w-6xl px-6 pb-20">{children}</div>
      )}
    </section>
  );
}

function Note({
  title,
  body,
  accent = false,
}: {
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div className="wf-note p-4">
      <div
        className="mb-2 text-[0.6rem] uppercase tracking-[0.16em]"
        style={{ color: accent ? "var(--wf-accent)" : "var(--wf-muted)" }}
      >
        {title}
      </div>
      <p
        className="text-[0.8rem] leading-relaxed"
        style={{ color: "var(--wf-muted)" }}
      >
        {body}
      </p>
    </div>
  );
}
