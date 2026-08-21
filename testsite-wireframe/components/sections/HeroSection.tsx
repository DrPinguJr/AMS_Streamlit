import {
  WireBox,
  WireButton,
  WireHeading,
  WireLines,
} from "@/components/wireframe/Primitives";

/**
 * 01 — Hero. Deliberately the plain one: a two-column grid that stacks on
 * mobile. No scroll logic.
 */
export function HeroSection() {
  return (
    <div className="grid items-center gap-12 lg:grid-cols-2">
      <div>
        <span className="wf-chip">Eyebrow / tagline</span>

        <div className="mt-6">
          <WireHeading />
        </div>

        <div className="mt-6 max-w-md">
          <WireLines count={3} />
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <WireButton variant="solid">Primary CTA</WireButton>
          <WireButton>Secondary</WireButton>
        </div>
      </div>

      <WireBox label="Hero media 16:9" className="aspect-video w-full" />
    </div>
  );
}
