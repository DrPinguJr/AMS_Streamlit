/**
 * SECTION REGISTRY
 *
 * This is the spine of the site. Every section is declared here exactly once,
 * and both the nav and the page body are generated from this array.
 *
 * To add a section:
 *   1. Build the component in `components/sections/`.
 *   2. Add an entry below.
 *   3. Register the component in the `SECTION_COMPONENTS` map in `app/page.tsx`.
 *
 * Reorder the array and the page order + nav order move together. Delete an
 * entry and the section disappears from both. Nothing else needs touching.
 */

export type SectionMeta = {
  /** Anchor id — the nav links to `#${id}`. */
  id: string;
  /** Short label used in the hamburger menu. */
  navLabel: string;
  /** Zero-padded index shown in the wireframe chip. */
  index: string;
  /** Section heading. */
  title: string;
  /** Plain-English: what this section is FOR. */
  purpose: string;
  /** Plain-English: HOW the effect is built, for whoever picks this up next. */
  mechanic: string;
};

export const SECTIONS: SectionMeta[] = [
  {
    id: "hero",
    navLabel: "Hero",
    index: "01",
    title: "Hero",
    purpose:
      "The standard opener. Headline, one line of supporting copy, two calls to action, and a piece of hero media on the right.",
    mechanic:
      "Plain responsive two-column grid — stacks to one column under 1024px. No scroll logic, no JS. This is the boring, reliable one.",
  },
  {
    id: "pinned",
    navLabel: "Pinned scroll",
    index: "02",
    title: "Pinned / finite scroll",
    purpose:
      "The section locks to the viewport and its panels move sideways as you scroll. When the panels run out, the lock releases and the page carries on to the next section.",
    mechanic:
      "A tall outer wrapper (panels x 100vh) holds a `sticky top-0 h-screen` inner box. Scroll progress through the wrapper is written to a CSS variable `--p`, and the panel track translates by `--p x (panels - 1) x -100vw`. Vertical scroll distance maps 1:1 to horizontal travel.",
  },
  {
    id: "converge",
    navLabel: "Converge",
    index: "03",
    title: "Images converge on scroll",
    purpose:
      "Media starts scattered, rotated and faded around the viewport, then flies together into a clean grid as you scroll through the section.",
    mechanic:
      "Same `--p` progress variable. Each tile carries its own `--dx`, `--dy` and `--r` offsets and interpolates them toward zero with `calc(var(--dx) * (1 - var(--p)))`. All motion is CSS — JS only ever writes one number.",
  },
  {
    id: "marquee",
    navLabel: "Marquee",
    index: "04",
    title: "Infinite floating marquee",
    purpose:
      "A continuously looping strip of mixed text and images. Two rows running in opposite directions, each item gently bobbing on its own timing.",
    mechanic:
      "The item list is rendered twice inside one track; the track animates to `translateX(-50%)`, which lands on an identical frame so the loop is seamless. A second `bob` keyframe on each item adds staggered vertical float. Pure CSS keyframes — no scroll listener, no animation library. Hover pauses it.",
  },
  {
    id: "stack",
    navLabel: "Card stack",
    index: "05",
    title: "Sticky card stack",
    purpose:
      "Cards pile up on top of one another as you scroll, each one sliding over the last. Good for process steps, feature tiers, or a short narrative.",
    mechanic:
      "Every card is `position: sticky` with a progressively larger `top` offset and a slight scale step. That is the entire trick — no JS at all.",
  },
  {
    id: "grid",
    navLabel: "Content grid",
    index: "06",
    title: "Content grid",
    purpose:
      "The workhorse. A straight responsive card grid for features, services, logos or posts — the section you will reach for most often.",
    mechanic:
      "CSS grid, `repeat(auto-fit, minmax(...))`. Included as the baseline case: not every section needs a scroll effect, and this one proves the shell works without one.",
  },
];
