"use client";

import { useEffect, useState } from "react";
import { SECTIONS } from "@/lib/sections";

/**
 * Sticky top bar + hamburger overlay menu.
 *
 * The menu is generated from the section registry, so a new section appears
 * here automatically. A scroll-spy keeps the current section labelled in the
 * bar and highlighted in the menu.
 */
export function Nav() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string>(SECTIONS[0]?.id ?? "");

  // Scroll-spy: whichever section crosses the middle of the viewport wins.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );

    for (const section of SECTIONS) {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, []);

  // Close on Escape, and stop the page scrolling behind the open menu.
  useEffect(() => {
    if (!open) return;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };

    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);

    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const activeMeta = SECTIONS.find((s) => s.id === active);

  return (
    <>
      <header
        className="sticky top-0 z-50 backdrop-blur"
        style={{
          height: "var(--wf-nav-h)",
          borderBottom: "1px solid var(--wf-line)",
          background: "color-mix(in srgb, var(--wf-bg) 85%, transparent)",
        }}
      >
        <nav className="mx-auto flex h-full w-full max-w-6xl items-center justify-between px-6">
          <a href="#top" className="text-sm tracking-[0.18em] uppercase">
            Testsite
          </a>

          <div className="flex items-center gap-4">
            {/* Current section readout — hidden on small screens. */}
            <span
              className="hidden text-[0.65rem] uppercase tracking-[0.14em] sm:block"
              style={{ color: "var(--wf-muted)" }}
            >
              {activeMeta ? `${activeMeta.index} / ${activeMeta.navLabel}` : ""}
            </span>

            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-controls="wf-menu"
              aria-label={open ? "Close menu" : "Open menu"}
              className="flex h-9 w-9 flex-col items-center justify-center gap-[5px] rounded-md"
              style={{ border: "1px solid var(--wf-line-strong)" }}
            >
              {/* 1.5px bars with a 5px gap sit 6.5px apart, so that is exactly
                  how far the outer two travel to meet in the middle. */}
              <Bar rotate={open ? 45 : 0} shift={open ? 6.5 : 0} />
              <Bar fade={open} />
              <Bar rotate={open ? -45 : 0} shift={open ? -6.5 : 0} />
            </button>
          </div>
        </nav>
      </header>

      {/* Overlay menu */}
      <div
        id="wf-menu"
        hidden={!open}
        className="fixed inset-0 z-40 overflow-y-auto pt-[var(--wf-nav-h)]"
        style={{ background: "var(--wf-bg)" }}
      >
        <ul className="mx-auto w-full max-w-6xl px-6 py-10">
          {SECTIONS.map((section) => {
            const isActive = section.id === active;

            return (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  onClick={() => setOpen(false)}
                  className="group flex items-baseline gap-5 py-5"
                  style={{ borderBottom: "1px solid var(--wf-line)" }}
                >
                  <span
                    className="text-[0.7rem] tracking-[0.14em]"
                    style={{
                      color: isActive ? "var(--wf-accent)" : "var(--wf-muted)",
                    }}
                  >
                    {section.index}
                  </span>

                  <span className="flex-1">
                    <span
                      className="block text-2xl tracking-tight sm:text-3xl"
                      style={{
                        color: isActive ? "var(--wf-accent)" : "var(--wf-ink)",
                      }}
                    >
                      {section.title}
                    </span>
                    <span
                      className="mt-1 block max-w-xl text-[0.75rem] leading-relaxed"
                      style={{ color: "var(--wf-muted)" }}
                    >
                      {section.purpose}
                    </span>
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}

/** One line of the hamburger icon, which morphs into an X when open. */
function Bar({
  rotate = 0,
  shift = 0,
  fade = false,
}: {
  rotate?: number;
  shift?: number;
  fade?: boolean;
}) {
  return (
    <span
      className="block h-[1.5px] w-4 transition-all duration-200"
      style={{
        background: "var(--wf-ink)",
        opacity: fade ? 0 : 1,
        transform: `translateY(${shift}px) rotate(${rotate}deg)`,
      }}
    />
  );
}
