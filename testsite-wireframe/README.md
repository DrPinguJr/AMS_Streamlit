# Testsite — a one-page section framework

A single-page Next.js site built as an **annotated wireframe**. Every block is a
reusable section pattern, drawn in greyscale placeholders so the structure and
the scroll behaviour read clearly before any visual design exists.

No subpages. No routes. One `app/page.tsx`.

```bash
npm install
npm run dev      # http://localhost:3000
```

## The idea

Sections are declared **once**, in `lib/sections.ts`. That single array drives
three things at the same time:

- the order sections render on the page
- the hamburger menu
- the footer's "Sections" column

Reorder the array and everything moves together. Delete an entry and the
section disappears from all three. That is the whole framework.

### Adding a section

1. Build the component in `components/sections/MySection.tsx`.
2. Add an entry to `SECTIONS` in `lib/sections.ts` — including `purpose` and
   `mechanic`, which become the two annotation notes on the page.
3. Register it in the `SECTION_COMPONENTS` map in `app/page.tsx`.
4. If it manages its own full-bleed width, add its id to `BLEED` in the same file.

## The sections

| # | Section | Pattern |
|---|---------|---------|
| 01 | Hero | Plain two-column grid. No scroll logic — the reliable one. |
| 02 | Pinned / finite scroll | Section locks to the viewport, panels move sideways, then the page continues. |
| 03 | Converge | Scattered media flies together into a grid as you scroll. |
| 04 | Marquee | Seamless infinite strip of mixed text and images, each item bobbing. |
| 05 | Card stack | Sticky cards pile on top of one another. Zero JS. |
| 06 | Content grid | The workhorse responsive card grid. |

## How the scroll effects work

Sections 02 and 03 share one mechanic, in `hooks/useScrollProgress.ts`:

> Measure how far the section has travelled through its own pinned range, and
> write that `0 → 1` number to a CSS custom property `--p` on the section.

The hook writes the value directly to the DOM inside `requestAnimationFrame` —
it deliberately does **not** use React state, so scrolling never triggers a
re-render. Children then animate purely in CSS by reading `var(--p)`:

```css
/* horizontal panel track (section 02) */
transform: translate3d(calc(var(--p) * (var(--panels) - 1) * -100vw), 0, 0);

/* per-tile convergence (section 03) */
transform: translate3d(calc(var(--dx) * (1 - var(--p))), ...);
```

JS only ever writes one number per frame. Everything else is CSS.

Sections 04, 05 and 06 use no JS at all — the marquee and the card stack are
pure CSS keyframes and `position: sticky` respectively.

### The marquee's seamless loop

Each row renders its item list **twice** inside one track, then animates the
track to `translateX(-50%)`. Because the second half is identical to the first,
the end of the animation lands on a pixel-identical frame and the loop has no
visible seam.

One gotcha worth keeping: item spacing lives on the items (`mr-5`), **not** as a
`gap` on the track. A `gap` adds an extra half-space between the two copies,
which knocks the `-50%` off and reintroduces the seam.

## Wireframe layer

The greyscale look is the point — it stops the conversation being about colour
while the structure is still being decided.

- `components/wireframe/Primitives.tsx` — `WireBox` (crossed placeholder image),
  `WireLines` (copy bars), `WireButton`, `WireHeading`.
- `components/wireframe/SectionShell.tsx` — wraps each section with its anchor,
  its numbered chip, and the two annotation notes.

When this becomes a real design, delete the `<header>` block in `SectionShell`
and the shell collapses to a plain `<section>`.

## Theming

Six CSS variables in `app/globals.css` control the entire palette, with a dark
variant under `prefers-color-scheme: dark`:

```
--wf-bg  --wf-panel  --wf-line  --wf-line-strong  --wf-fill  --wf-ink
--wf-muted  --wf-accent
```

## Accessibility

- `prefers-reduced-motion` disables the marquee and the bob, and lands the
  converge tiles in their finished state.
- The duplicated half of each marquee row is `aria-hidden`.
- The hamburger reports `aria-expanded` / `aria-controls`, closes on `Escape`,
  and locks background scroll while open.

## Stack

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · zero
animation libraries.
