import Link from "next/link";
import { ChevronRight, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

/* Fil d'Ariane stylé */
export function Breadcrumbs({ items }: { items: Array<{ label: string; href?: string }> }) {
  return (
    <nav aria-label="Fil d'Ariane" className="flex flex-wrap items-center gap-1 text-xs text-brand-charcoal">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3 w-3 opacity-40" />}
          {it.href ? (
            <Link href={it.href} className="transition-colors hover:text-brand-gold-dark">
              {it.label}
            </Link>
          ) : (
            <span className="text-brand-charcoal">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

/* Bandeau hero premium (blanc × or) pleine largeur */
export function SeoHero({
  eyebrow,
  title,
  accent,
  lead,
  breadcrumbs,
  chips,
  children,
}: {
  eyebrow?: string;
  title: ReactNode;
  accent?: string;
  lead?: ReactNode;
  breadcrumbs?: Array<{ label: string; href?: string }>;
  chips?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="relative overflow-hidden border-b border-amber-100/70 gradient-hero-v2">
      <div className="pointer-events-none absolute inset-0 grid-lines opacity-50" />
      <div className="relative mx-auto max-w-5xl px-4 py-12 sm:py-16">
        {breadcrumbs && (
          <div className="mb-5">
            <Breadcrumbs items={breadcrumbs} />
          </div>
        )}
        {eyebrow && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-brand-gold-dark">
            {eyebrow}
          </span>
        )}
        <h1 className="mt-4 font-display text-3xl font-bold tracking-tight text-brand-dark sm:text-[2.6rem] sm:leading-[1.1]">
          {title} {accent && <span className="text-gradient">{accent}</span>}
        </h1>
        {lead && (
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-brand-charcoal sm:text-base">{lead}</p>
        )}
        {chips && <div className="mt-5 flex flex-wrap gap-2">{chips}</div>}
        {children}
      </div>
    </header>
  );
}

/* Conteneur de contenu standard */
export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto max-w-4xl px-4 py-10 sm:py-12 ${className}`}>{children}</div>;
}

/* Section avec titre + barre dorée */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10 first:mt-0">
      <h2 className="flex items-center gap-2.5 font-display text-xl font-bold tracking-tight text-brand-dark sm:text-2xl">
        <span className="h-5 w-1 rounded-full bg-gradient-gold" aria-hidden />
        {title}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/* Carte-lien (glass) : icône optionnelle, titre, description, méta */
export function LinkCard({
  href,
  title,
  desc,
  meta,
  accent,
  icon,
}: {
  href: string;
  title: string;
  desc?: ReactNode;
  meta?: ReactNode;
  accent?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <Link href={href} className="glass-card group block rounded-2xl p-5">
      <div className="flex items-start gap-3">
        {icon && (
          <span className="icon-box flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-gold-soft text-brand-gold-dark">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          {meta && <div className="mb-1 text-[11px] text-brand-charcoal">{meta}</div>}
          <h2 className="font-display text-base font-semibold text-brand-dark transition-colors group-hover:text-brand-gold-dark">
            {title}
          </h2>
          {desc && <p className="mt-1 text-sm leading-relaxed text-brand-charcoal">{desc}</p>}
          {accent && <div className="mt-2 text-xs font-medium text-brand-gold-dark">{accent}</div>}
        </div>
        <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-brand-gold-dark/50 transition-all group-hover:translate-x-0.5 group-hover:text-brand-gold-dark" />
      </div>
    </Link>
  );
}

/* Encart CTA doré */
export function Callout({
  children,
  href,
  cta,
}: {
  children: ReactNode;
  href?: string;
  cta?: string;
}) {
  return (
    <div className="mt-10 overflow-hidden rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-5 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm leading-relaxed text-brand-charcoal">{children}</p>
        {href && cta && (
          <Link
            href={href}
            className="btn-shimmer inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-gradient-gold px-4 py-2.5 text-sm font-semibold text-brand-dark shadow-sm transition-transform hover:scale-[1.02]"
          >
            {cta} <ArrowRight className="h-4 w-4" />
          </Link>
        )}
      </div>
    </div>
  );
}

/* Petit chip */
export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "gold" }) {
  const cls =
    tone === "gold"
      ? "border-amber-200 bg-amber-50 text-brand-gold-dark"
      : "border-gray-200 bg-white text-brand-charcoal";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}>
      {children}
    </span>
  );
}

/* Carte définition (terme + texte) */
export function DefCard({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="card-hover rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="font-display text-[15px] font-semibold text-brand-dark">{term}</h3>
      <p className="mt-1 text-sm leading-relaxed text-brand-charcoal">{children}</p>
    </div>
  );
}
