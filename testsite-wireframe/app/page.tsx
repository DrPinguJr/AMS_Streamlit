import type { ComponentType } from "react";
import { SECTIONS } from "@/lib/sections";
import { SectionShell } from "@/components/wireframe/SectionShell";
import { HeroSection } from "@/components/sections/HeroSection";
import { PinnedSection } from "@/components/sections/PinnedSection";
import { ConvergeSection } from "@/components/sections/ConvergeSection";
import { MarqueeSection } from "@/components/sections/MarqueeSection";
import { StackSection } from "@/components/sections/StackSection";
import { GridSection } from "@/components/sections/GridSection";

/**
 * Maps a registry id to the component that renders it.
 * Add a section: create the component, add its entry to `lib/sections.ts`,
 * then add one line here.
 */
const SECTION_COMPONENTS: Record<string, ComponentType> = {
  hero: HeroSection,
  pinned: PinnedSection,
  converge: ConvergeSection,
  marquee: MarqueeSection,
  stack: StackSection,
  grid: GridSection,
};

/**
 * Sections that manage their own full-bleed width — anything using a sticky
 * viewport-height box or an edge-to-edge track.
 */
const BLEED = new Set(["pinned", "converge", "marquee"]);

export default function Home() {
  return (
    <>
      <Intro />

      {SECTIONS.map((meta) => {
        const Section = SECTION_COMPONENTS[meta.id];
        if (!Section) return null;

        return (
          <SectionShell key={meta.id} meta={meta} bleed={BLEED.has(meta.id)}>
            <Section />
          </SectionShell>
        );
      })}
    </>
  );
}

/** Explains the whole document before the first section. */
function Intro() {
  return (
    <div id="top" className="wf-grid-bg">
      <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-28">
        <span className="wf-chip">Wireframe / v0</span>

        <h1 className="mt-6 max-w-3xl text-3xl leading-tight tracking-tight sm:text-5xl">
          A one-page section framework
        </h1>

        <p
          className="mt-5 max-w-2xl text-sm leading-relaxed"
          style={{ color: "var(--wf-muted)" }}
        >
          Every block below is a self-contained, reusable section pattern, drawn
          as a wireframe so the structure and the scroll behaviour read clearly
          before any visual design exists. Each one is annotated with what it is
          for and how it is built.
        </p>

        <p
          className="mt-4 max-w-2xl text-sm leading-relaxed"
          style={{ color: "var(--wf-muted)" }}
        >
          Sections are declared once in{" "}
          <code style={{ color: "var(--wf-accent)" }}>lib/sections.ts</code> —
          that single array drives the page order, the hamburger menu and the
          footer links together. Add, remove or reorder an entry and all three
          follow.
        </p>

        <dl className="mt-10 grid max-w-2xl gap-4 sm:grid-cols-3">
          <Stat value={String(SECTIONS.length)} label="Section patterns" />
          <Stat value="1" label="Page, no routes" />
          <Stat value="0" label="Animation libraries" />
        </dl>
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="wf-note p-4">
      <dt className="text-2xl">{value}</dt>
      <dd
        className="mt-1 text-[0.65rem] uppercase tracking-[0.14em]"
        style={{ color: "var(--wf-muted)" }}
      >
        {label}
      </dd>
    </div>
  );
}
