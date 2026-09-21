import type { ReactNode } from "react";
import Link from "next/link";

/**
 * Kit de mise en page des articles.
 *
 * Trois règles ont dicté ces composants, et elles expliquent ce qu'on n'y trouve pas :
 *
 * 1. **Tout est rendu par le serveur, sans une ligne de JavaScript.** Un graphique en
 *    <canvas> ou une bibliothèque de charts ne serait lu ni par un robot d'indexation,
 *    ni par un lecteur d'écran, ni par un navigateur qui a coupé les scripts. Les
 *    visuels sont donc du SVG écrit en clair, avec leurs valeurs en texte à côté.
 * 2. **Aucun élément décoratif vide.** Chaque bloc porte une information que le lecteur
 *    perdrait s'il disparaissait : un chiffre, une comparaison, une mise en garde.
 * 3. **Le balisage suit ce qui est affiché.** Un tableau de données est un `<table>`
 *    avec un `<caption>`, une liste est une `<ul>` — pas des `<div>` empilés.
 *
 * Les styles de `blog-prose` (globals.css) s'appliquent au corps du texte ; ces blocs
 * s'en isolent par la classe `bp-bloc`, sans quoi la typographie d'article écraserait
 * leurs marges et leurs tailles.
 */

/* ───────────────────────────── Chapô ───────────────────────────── */
/** Le paragraphe d'attaque, détaché du corps : il porte la promesse de l'article. */
export function Chapo({ children }: { children: ReactNode }) {
  return (
    <div className="bp-bloc my-6 border-l-[3px] border-brand-gold pl-5">
      <p className="font-display text-[17px] leading-[1.65] text-brand-dark sm:text-[18px]">
        {children}
      </p>
    </div>
  );
}

/* ──────────────────────────── Chiffres clés ──────────────────────────── */
export interface ChiffreItem {
  valeur: string;
  libelle: string;
  /** Précision facultative : la population, la période, l'unité. */
  detail?: string;
}

/**
 * Les chiffres qui portent l'article, visibles avant la lecture.
 *
 * C'est le bloc que lit un visiteur pressé, et celui que Google cite le plus volontiers :
 * une valeur, ce qu'elle mesure, et sur quoi elle est mesurée.
 */
export function Chiffres({ items, source }: { items: ChiffreItem[]; source?: string }) {
  return (
    <div className="bp-bloc my-7">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-gray-200 bg-gray-200 sm:grid-cols-4">
        {items.map((c) => (
          <div key={c.libelle} className="bg-white px-4 py-4">
            <dd className="font-display text-[22px] font-bold leading-none tracking-tight text-brand-dark tabular-nums sm:text-[25px]">
              {c.valeur}
            </dd>
            <dt className="mt-1.5 text-[12.5px] leading-snug text-brand-charcoal">{c.libelle}</dt>
            {c.detail && <p className="mt-1 text-[11px] leading-snug text-gray-500">{c.detail}</p>}
          </div>
        ))}
      </dl>
      {source && <p className="mt-2 text-[11.5px] text-gray-500">{source}</p>}
    </div>
  );
}

/* ─────────────────────────── Graphique en barres ─────────────────────────── */
export interface Barre {
  label: string;
  valeur: number;
  /** Texte affiché à droite de la barre. À défaut, la valeur suivie de `unite`. */
  affichage?: string;
  /** Met la barre en avant — une seule par graphique, sinon plus rien ne ressort. */
  accent?: boolean;
}

/**
 * Un graphique en barres horizontal, en HTML et CSS.
 *
 * Pourquoi pas une bibliothèque de charts : elle dessinerait côté navigateur, donc
 * invisible pour un robot d'indexation et pour un lecteur d'écran, et ajouterait cent
 * kilo-octets de JavaScript à une page qui n'en a pas besoin.
 *
 * Pourquoi pas du SVG non plus — c'était la première version, et elle était illisible sur
 * téléphone. Un SVG se met à l'échelle de son conteneur : un texte de 17 unités dans une
 * grille de 700 tombe sous 7 pixels sur un écran de 375. Le mobile pèse 73 % des
 * impressions du site, donc ce compromis n'en était pas un.
 *
 * Ici, **la donnée est du texte** — libellé et valeur, à leur taille normale, dans une
 * liste de définitions. La barre n'est qu'un rectangle décoratif derrière, masqué aux
 * lecteurs d'écran. Le graphique reste donc exact même sans CSS, sans images et sans
 * JavaScript, et lisible à toutes les largeurs.
 */
export function Barres({
  titre,
  legende,
  barres,
  unite = "%",
  max,
  source,
}: {
  titre: string;
  legende?: string;
  barres: Barre[];
  unite?: string;
  max?: number;
  source?: string;
}) {
  const plafond = max ?? Math.max(...barres.map((b) => Math.abs(b.valeur))) * 1.08;

  return (
    <figure className="bp-bloc my-7 rounded-2xl border border-gray-200 bg-white p-5 sm:p-6">
      <figcaption>
        <p className="font-display text-[15px] font-bold leading-snug text-brand-dark">{titre}</p>
        {legende && <p className="mt-1.5 text-[12.5px] leading-snug text-brand-charcoal">{legende}</p>}
      </figcaption>

      <dl className="mt-4 space-y-3.5">
        {barres.map((b) => {
          const part = Math.min(100, (Math.abs(b.valeur) / plafond) * 100);
          return (
            <div key={b.label}>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[13.5px] leading-snug text-brand-charcoal">{b.label}</dt>
                <dd
                  className={`shrink-0 font-display text-[15px] tabular-nums ${
                    b.accent ? "font-bold text-brand-gold-dark" : "font-semibold text-brand-dark"
                  }`}
                >
                  {b.affichage ?? `${fr(b.valeur)} ${unite}`}
                </dd>
              </div>
              {/* Décoratif : la valeur est déjà écrite juste au-dessus. */}
              <div className="mt-1.5 h-3 w-full overflow-hidden rounded-full bg-gray-100" aria-hidden="true">
                <div
                  className={`h-full rounded-full ${b.accent ? "bg-brand-gold-dark" : "bg-brand-amber"}`}
                  style={{ width: `${part}%` }}
                />
              </div>
            </div>
          );
        })}
      </dl>

      {source && <p className="mt-3.5 text-[11.5px] leading-snug text-gray-500">{source}</p>}
    </figure>
  );
}

/* ──────────────────────────── Encadré ──────────────────────────── */
const TONS = {
  info: { bord: "border-gray-200", fond: "bg-gray-50/70", titre: "text-brand-dark" },
  cle: { bord: "border-amber-200", fond: "bg-amber-50/50", titre: "text-brand-gold-dark" },
  garde: { bord: "border-red-200", fond: "bg-red-50/40", titre: "text-brand-red" },
} as const;

/** Un aparté : à retenir, mise en garde, précision de méthode. */
export function Encadre({
  titre,
  ton = "cle",
  children,
}: {
  titre: string;
  ton?: keyof typeof TONS;
  children: ReactNode;
}) {
  const t = TONS[ton];
  return (
    <aside className={`bp-bloc my-6 rounded-2xl border ${t.bord} ${t.fond} p-5`}>
      <p
        className={`font-display text-[12px] font-bold uppercase tracking-[0.08em] ${t.titre}`}
      >
        {titre}
      </p>
      <div className="mt-2 space-y-2 text-[14.5px] leading-[1.7] text-brand-charcoal">{children}</div>
    </aside>
  );
}

/* ──────────────────────────── Comparatif ──────────────────────────── */
/** Deux objets mis face à face, critère par critère. Un vrai tableau, pas des colonnes. */
export function Comparatif({
  titre,
  colonnes,
  lignes,
}: {
  titre: string;
  colonnes: [string, string];
  lignes: Array<{ critere: string; a: ReactNode; b: ReactNode }>;
}) {
  return (
    <div className="bp-bloc bp-comparatif my-7 overflow-x-auto">
      <table className="w-full border-collapse text-[14px] sm:min-w-[520px]">
        <caption className="mb-3 text-left font-display text-[15px] font-bold text-brand-dark">
          {titre}
        </caption>
        <thead>
          <tr>
            <th className="w-[30%] border-b border-gray-200 px-3 py-2.5 text-left text-[12px] font-semibold uppercase tracking-wide text-gray-500">
              &nbsp;
            </th>
            <th className="border-b border-gray-200 px-3 py-2.5 text-left text-[12.5px] font-semibold text-brand-charcoal">
              {colonnes[0]}
            </th>
            <th className="border-b-2 border-brand-gold px-3 py-2.5 text-left text-[12.5px] font-semibold text-brand-gold-dark">
              {colonnes[1]}
            </th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((l) => (
            <tr key={l.critere} className="align-top">
              <th
                scope="row"
                className="border-b border-gray-100 px-3 py-3 text-left text-[13px] font-semibold text-brand-dark"
              >
                {l.critere}
              </th>
              <td
                data-col={colonnes[0]}
                className="border-b border-gray-100 px-3 py-3 leading-relaxed text-brand-charcoal"
              >
                {l.a}
              </td>
              <td
                data-col={colonnes[1]}
                className="border-b border-gray-100 bg-amber-50/40 px-3 py-3 leading-relaxed text-brand-charcoal"
              >
                {l.b}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ──────────────────────────── Sommaire ──────────────────────────── */
/**
 * Le sommaire d'un article long.
 *
 * Il sert d'abord le lecteur, qui voit en dix lignes ce que la page couvre. Il donne
 * aussi à chaque section une ancre stable : un lien externe peut viser un passage précis,
 * et Google peut proposer ces passages comme liens de site sous le résultat.
 */
export function Sommaire({ items }: { items: Array<{ id: string; label: string }> }) {
  return (
    <nav className="bp-bloc my-7 rounded-2xl border border-gray-200 bg-gray-50/60 p-5" aria-label="Sommaire">
      <p className="font-display text-[12px] font-bold uppercase tracking-[0.08em] text-brand-charcoal">
        Au sommaire
      </p>
      <ol className="mt-3 space-y-1.5">
        {items.map((it, i) => (
          <li key={it.id} className="text-[14px] leading-snug">
            <span className="mr-2 font-display text-[12px] font-bold text-brand-gold-dark tabular-nums">
              {String(i + 1).padStart(2, "0")}
            </span>
            <a
              href={`#${it.id}`}
              className="text-brand-charcoal underline-offset-2 hover:text-brand-gold-dark hover:underline"
            >
              {it.label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Un titre de section ancrable — le pendant du sommaire. */
export function H2({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-24">
      {children}
    </h2>
  );
}

/* ──────────────────────────── Méthode ──────────────────────────── */
/**
 * Le bloc de méthode, en fin d'article.
 *
 * Il dit d'où viennent les chiffres, sur quelle période, et surtout ce qui a été ÉCARTÉ.
 * C'est ce qui sépare une mesure d'une affirmation, et c'est vérifiable par n'importe qui.
 */
export function Methode({ children }: { children: ReactNode }) {
  return (
    <section className="bp-bloc mt-9 rounded-2xl border border-gray-200 bg-gray-50/60 p-5">
      <p className="font-display text-[12px] font-bold uppercase tracking-[0.08em] text-brand-charcoal">
        Méthode et sources
      </p>
      <div className="mt-2 space-y-2 text-[13px] leading-[1.65] text-gray-600">{children}</div>
    </section>
  );
}

/* ──────────────────────────── Appel à l'action ──────────────────────────── */
/** Un renvoi en fin de section, quand la suite logique est une page du site. */
export function Suite({ href, cta, children }: { href: string; cta: string; children: ReactNode }) {
  return (
    <div className="bp-bloc my-6 flex flex-col gap-3 rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-5 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-[14.5px] leading-relaxed text-brand-charcoal">{children}</p>
      <Link
        href={href}
        className="inline-flex shrink-0 items-center justify-center rounded-xl bg-brand-dark px-4 py-2.5 text-[13.5px] font-semibold text-white transition-colors hover:bg-brand-gold-dark"
      >
        {cta}
      </Link>
    </div>
  );
}

/* ──────────────────────────── Utilitaires ──────────────────────────── */
const fr = (n: number) => n.toLocaleString("fr-FR");
const slug = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
