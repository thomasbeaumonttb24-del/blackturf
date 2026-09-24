import Link from "next/link";
import { Database, Trophy, Target, TrendingDown, ScrollText, AlertTriangle, ArrowUpRight } from "lucide-react";
import { jourCourtAnnee, type SeoTrackRecord } from "@/lib/seo";

/**
 * Résumé du palmarès, rendu côté serveur.
 *
 * La page `/track-record` est une application cliente : son HTML ne contenait qu'un
 * squelette, ce qui justifiait son `noindex`. Ce bloc porte les mêmes chiffres en clair
 * dans le document servi.
 *
 * Deux règles de rédaction, tenues par le reste du site :
 *   — on ne vend jamais un gain. Le rendement réel est publié tel quel, négatif compris,
 *     et le prélèvement du PMU est rappelé pour que le lecteur sache à quoi il se mesure ;
 *   — un taux ne veut rien dire seul : chaque chiffre est mis en regard de ce que
 *     donnerait un tirage au sort sur les mêmes courses.
 *
 * Si l'API ne répond pas, le bloc garde son texte explicatif : la page n'est jamais vide.
 */
export function PalmaresResume({ tr }: { tr: SeoTrackRecord | null }) {
  const g = tr?.global;
  // Le repère publié est le HASARD, calculé sur le champ réel de chaque course.
  // La comparaison au classement par la cote a été retirée du site le 2026-09-08 :
  // elle reste mesurée côté API (`SeoTrackRecord.marche`), mais elle occupait les
  // pages publiques à expliquer que le marché est aussi précis que nous, ce qui
  // n'est pas le rôle d'une page qui doit faire essayer le produit.
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

  // Tuiles : valeur + repère hasard. `jauge` / `hasard` (0-100) dessinent une barre
  // statique : ce bloc est rendu côté serveur, il doit être complet sans script.
  const tuiles = g
    ? [
        {
          k: "Courses mesurées",
          v: g.nb_courses_analysees.toLocaleString("fr-FR"),
          s: g.mesure_depuis ? `depuis le ${jourCourtAnnee(g.mesure_depuis)}` : null,
          icon: Database, ton: "from-slate-700 to-slate-950 text-amber-300",
          jauge: null as number | null, hasard: null as number | null,
        },
        {
          k: "Gagnant trouvé",
          // Même champ que le hero du palmarès et que l'accueil :
          // `accuracy_top1` mesure le même évènement sur une autre table et
          // affichait 27,6 % ici pendant que les deux autres disaient 28,6 %.
          v: pct(g.favori_win_rate),
          s: `hasard : ${pct(g.hasard_top1)}`,
          icon: Trophy, ton: "from-emerald-400 to-emerald-700 text-white",
          jauge: g.favori_win_rate, hasard: g.hasard_top1,
        },
        {
          k: "Gagnant dans le trio de tête prédit",
          v: pct(g.accuracy_top3),
          s: `hasard : ${pct(g.hasard_top3)}`,
          icon: Target, ton: "from-amber-300 to-amber-600 text-slate-950",
          jauge: g.accuracy_top3, hasard: g.hasard_top3,
        },
        {
          k: "Rendement du favori de l'algorithme",
          v: pct(g.favori_roi),
          s: `sur ${g.nb_favoris_evalues.toLocaleString("fr-FR")} courses, 1 € Gagnant`,
          icon: TrendingDown, ton: "from-rose-400 to-rose-600 text-white",
          jauge: null, hasard: null,
        },
      ]
    : [];

  return (
    <section className="bg-[#FCFBF8] pb-16 sm:pb-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
      <div className="relative overflow-hidden rounded-[2rem] bg-white shadow-[0_40px_90px_-60px_rgba(17,24,39,.55)] ring-1 ring-stone-200">
        {/* Bandeau d'en-tête sombre, même langage que la scène des records. */}
        <div className="relative isolate overflow-hidden bg-[#0b1020] px-5 py-8 sm:px-10 sm:py-10">
          <span className="pointer-events-none absolute -left-16 -top-20 -z-10 h-64 w-64 rounded-full bg-amber-500/25 blur-[90px]" aria-hidden="true" />
          <span className="pointer-events-none absolute -right-10 bottom-0 -z-10 h-48 w-48 rounded-full bg-indigo-500/20 blur-[80px]" aria-hidden="true" />
          <span className="inline-flex items-center gap-2 rounded-full bg-amber-400/10 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-amber-300 ring-1 ring-amber-400/25">
            <ScrollText className="h-3.5 w-3.5" aria-hidden="true" /> En toutes lettres
          </span>
          <h2 className="mt-3 font-display text-[1.65rem] font-extrabold leading-tight tracking-tight text-white sm:text-4xl">
            Ce que mesure cette page
          </h2>
          <p className="mt-3 max-w-3xl text-[15px] leading-7 text-white/75">
            Chaque course analysée par BlackTurf est notée après l&apos;arrivée, aux rapports
            officiels du PMU. Le classement prédit est comparé au classement réel, et la
            probabilité annoncée pour chaque cheval est confrontée à ce qui s&apos;est produit.
            Les périodes perdantes sont comptées comme les autres.
          </p>
        </div>

        <div className="p-5 sm:p-10">
        {g ? (
          <>
            <dl className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4 lg:gap-4">
              {tuiles.map((c) => (
                <div
                  key={c.k}
                  className="group relative rounded-2xl bg-gradient-to-b from-white to-stone-50 p-4 ring-1 ring-stone-200 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_24px_40px_-28px_rgba(180,83,9,.6)] hover:ring-amber-300 sm:p-5"
                >
                  <span className={`inline-flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br shadow-[inset_0_1px_0_rgba(255,255,255,.35),0_10px_18px_-10px_rgba(0,0,0,.5)] ${c.ton}`}>
                    <c.icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <dt className="mt-4 text-xs font-semibold leading-snug text-brand-charcoal">{c.k}</dt>
                  {/* La précision vit DANS le <dd> : un <div> nu glissé entre deux
                      paires dt/dd rend la liste de définitions mal formée (règle axe
                      « definition-list », −7 points d'accessibilité), et c'est bien
                      une précision de la même valeur, pas un troisième terme. */}
                  <dd className="mt-1 font-display text-3xl font-black tabular-nums text-brand-dark">
                    {c.v}
                    {c.jauge != null && (
                      <span className="relative mt-3 block h-2 overflow-hidden rounded-full bg-stone-200/80" aria-hidden="true">
                        <span className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-300 to-amber-600" style={{ width: `${Math.min(c.jauge, 100)}%` }} />
                        {c.hasard != null && <span className="absolute inset-y-0 w-0.5 bg-slate-700" style={{ left: `${Math.min(c.hasard, 100)}%` }} />}
                      </span>
                    )}
                    {c.s && (
                      <span className="mt-1.5 block font-sans text-[11px] font-normal text-brand-charcoal">
                        {c.s}
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>

            <p className="mt-6 max-w-4xl text-[15px] leading-7 text-brand-charcoal">
              Sur {g.nb_courses_analysees.toLocaleString("fr-FR")} courses de{" "}
              {g.nb_partants_moyen.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} partants
              en moyenne, l&apos;algorithme désigne le gagnant {pct(g.favori_win_rate)} du temps, contre{" "}
              {pct(g.hasard_top1)} pour un tirage au sort, et le place dans son trio de tête{" "}
              {pct(g.accuracy_top3)} du temps contre {pct(g.hasard_top3)}.{" "}
              {g.brier_moyen !== null && g.brier_moyen !== undefined && (
                <>
                  Le score de Brier moyen, qui mesure la justesse des probabilités annoncées et
                  non le seul classement, s&apos;établit à{" "}
                  {g.brier_moyen.toLocaleString("fr-FR", { maximumFractionDigits: 4 })} — plus il
                  est bas, mieux les probabilités correspondent à la réalité.{" "}
                </>
              )}
              {g.nb_courses_rejouables > 0 && (
                <>
                  {g.nb_courses_rejouables.toLocaleString("fr-FR")} de ces courses sont rejouables à
                  l&apos;identique : le pronostic y a été figé avant le départ et conservé tel quel.
                </>
              )}
            </p>

            {g.favori_roi !== null && g.favori_roi !== undefined && (
              <div className="mt-5 flex gap-3 rounded-2xl bg-gradient-to-br from-amber-50 to-white p-4 ring-1 ring-amber-200 sm:p-5">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800 ring-1 ring-amber-200">
                  <AlertTriangle className="h-5 w-5" aria-hidden="true" />
                </span>
                <p className="text-sm leading-relaxed text-brand-charcoal">
                  <strong className="text-brand-dark">Ce que cela ne veut pas dire.</strong> Miser 1 €
                  Gagnant sur le favori de l&apos;algorithme, sur ces{" "}
                  {g.nb_favoris_evalues.toLocaleString("fr-FR")} courses, aurait rendu{" "}
                  {pct(g.favori_roi)} — autrement dit une perte. Le PMU prélève environ 20 % des
                  enjeux avant toute redistribution : le pari hippique est un jeu à somme négative,
                  et mieux classer les chevaux que le hasard ne suffit pas à le renverser. BlackTurf
                  mesure sa valeur par la qualité de son classement, jamais par un rendement promis.
                </p>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Les chiffres détaillés sont affichés plus haut, dès qu&apos;ils sont chargés. Ils portent
            sur l&apos;intégralité des courses analysées depuis la mise en service, sans sélection :
            le pari hippique est un jeu à somme négative — le PMU prélève environ 20 % des enjeux
            avant redistribution — et BlackTurf publie ses périodes perdantes comme ses périodes
            gagnantes.
          </p>
        )}

        <nav className="mt-6 flex flex-wrap gap-2 border-t border-stone-100 pt-5 text-[13px]" aria-label="Pour aller plus loin">
          {[
            { href: "/programme", txt: "Courses du jour" },
            { href: "/resultats", txt: "Résultats" },
            { href: "/pronostics-ia", txt: "Comment marche l’IA" },
            { href: "/guides/pari-de-valeur", txt: "Ce qu'est un pari de valeur" },
            { href: "/tarifs", txt: "Tarifs" },
          ].map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="group inline-flex min-h-10 items-center gap-1 rounded-full bg-stone-50 px-4 py-2 font-semibold text-brand-charcoal ring-1 ring-stone-200 transition-all hover:-translate-y-0.5 hover:bg-amber-50 hover:text-brand-gold-dark hover:ring-amber-300"
            >
              {l.txt}
              <ArrowUpRight className="h-3.5 w-3.5 opacity-50 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:opacity-100" aria-hidden="true" />
            </Link>
          ))}
        </nav>
        </div>
      </div>
      </div>
    </section>
  );
}
