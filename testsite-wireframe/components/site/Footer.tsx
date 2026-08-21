import { SECTIONS } from "@/lib/sections";
import { WireLines } from "@/components/wireframe/Primitives";

/**
 * Wireframe footer. The "Sections" column is generated from the registry;
 * the other two columns are placeholder link stacks.
 */
export function Footer() {
  return (
    <footer
      className="wf-grid-bg"
      style={{ borderTop: "1px solid var(--wf-line)" }}
    >
      <div className="mx-auto w-full max-w-6xl px-6 py-16">
        <div className="grid gap-12 md:grid-cols-4">
          {/* Brand block */}
          <div className="md:col-span-1">
            <div className="text-sm tracking-[0.18em] uppercase">Testsite</div>
            <p
              className="mt-3 text-[0.75rem] leading-relaxed"
              style={{ color: "var(--wf-muted)" }}
            >
              A single-page section framework, drawn as a wireframe.
            </p>
            <div className="mt-5">
              <WireLines count={2} />
            </div>
          </div>

          {/* Real links, straight from the registry */}
          <FooterColumn title="Sections">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="text-[0.75rem] hover:underline"
                  style={{ color: "var(--wf-muted)" }}
                >
                  {section.index} / {section.navLabel}
                </a>
              </li>
            ))}
          </FooterColumn>

          {/* Placeholder columns */}
          <FooterColumn title="Column two">
            <PlaceholderLinks count={5} />
          </FooterColumn>

          <FooterColumn title="Column three">
            <PlaceholderLinks count={4} />
          </FooterColumn>
        </div>

        <div
          className="mt-14 flex flex-col gap-4 pt-6 sm:flex-row sm:items-center sm:justify-between"
          style={{ borderTop: "1px solid var(--wf-line)" }}
        >
          <span
            className="text-[0.65rem] uppercase tracking-[0.14em]"
            style={{ color: "var(--wf-muted)" }}
          >
            Placeholder — legal / copyright line
          </span>

          <a
            href="#top"
            className="text-[0.65rem] uppercase tracking-[0.14em] hover:underline"
            style={{ color: "var(--wf-accent)" }}
          >
            Back to top ↑
          </a>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className="mb-4 text-[0.6rem] uppercase tracking-[0.16em]"
        style={{ color: "var(--wf-ink)" }}
      >
        {title}
      </div>
      <ul className="flex flex-col gap-2.5">{children}</ul>
    </div>
  );
}

function PlaceholderLinks({ count }: { count: number }) {
  const widths = ["70%", "55%", "80%", "48%", "64%"];

  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <li key={i}>
          <div className="wf-line" style={{ width: widths[i % widths.length] }} />
        </li>
      ))}
    </>
  );
}
