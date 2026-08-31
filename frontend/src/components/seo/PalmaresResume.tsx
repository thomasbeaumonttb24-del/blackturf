import Link from "next/link";
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
  // LE comparateur. Se mesurer au hasard flattait : battre un tirage au sort est la
  // moindre des choses pour un modèle. Le vrai adversaire est le classement par la
  // cote, et sur les mêmes 4 023 courses il est un peu MEILLEUR que nous en
  // précision (62,3 % contre 61,4 % de gagnants dans le trio de tête). Le publier
  // ne coûte rien à l'offre, il la déplace là où elle tient réellement.
  const m = tr?.marche ?? null;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

  return (
    <section className="mx-auto max-w-4xl px-4 pb-16 sm:px-6">
      <div className="rounded-2xl border border-gray-200 bg-white p-5 sm:p-7">
        <h2 className="font-display text-xl font-bold tracking-tight text-brand-dark sm:text-2xl">
          Ce que mesure ce palmarès
        </h2>

        <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
          Chaque course analysée par BlackTurf est notée après l&apos;arrivée, aux rapports
          officiels du PMU. Le classement prédit est comparé au classement réel, et la
          probabilité annoncée pour chaque cheval est confrontée à ce qui s&apos;est produit.
          Les périodes perdantes sont comptées comme les autres.
        </p>

        {g ? (
          <>
            <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-gray-200 bg-gray-200 sm:grid-cols-4">
              {[
                {
                  k: "Courses mesurées",
                  v: g.nb_courses_analysees.toLocaleString("fr-FR"),
                  s: g.mesure_depuis ? `depuis le ${jourCourtAnnee(g.mesure_depuis)}` : null,
                },
                {
                  k: "Gagnant trouvé",
                  v: pct(g.accuracy_top1),
                  s: m ? `marché : ${pct(m.marche_top1)}` : `hasard : ${pct(g.hasard_top1)}`,
                },
                {
                  k: "Gagnant dans le trio de tête prédit",
                  v: pct(g.accuracy_top3),
                  s: m ? `marché : ${pct(m.marche_top3)}` : `hasard : ${pct(g.hasard_top3)}`,
                },
                {
                  k: "Rendement du favori de l'algorithme",
                  v: pct(g.favori_roi),
                  s: `sur ${g.nb_favoris_evalues.toLocaleString("fr-FR")} courses, 1 € Gagnant`,
                },
              ].map((c) => (
                <div key={c.k} className="bg-white px-3.5 py-3">
                  <dt className="text-[11px] leading-snug text-brand-charcoal">{c.k}</dt>
                  <dd className="mt-1 font-display text-[19px] font-bold tabular-nums text-brand-dark">
                    {c.v}
                  </dd>
                  {c.s && <div className="mt-0.5 text-[11px] text-brand-charcoal">{c.s}</div>}
                </div>
              ))}
            </dl>

            <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
              Sur {g.nb_courses_analysees.toLocaleString("fr-FR")} courses de{" "}
              {g.nb_partants_moyen.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} partants
              en moyenne, l&apos;algorithme désigne le gagnant {pct(g.accuracy_top1)} du temps, contre{" "}
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

            {m && (
              <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
                <strong className="text-brand-dark">Et face au marché ?</strong> Sur les{" "}
                {m.nb_courses.toLocaleString("fr-FR")} mêmes courses, classer les chevaux par leur
                seule cote trouve le gagnant {pct(m.marche_top1)} du temps et le place dans son trio
                de tête {pct(m.marche_top3)} du temps — contre {pct(m.ia_top1)} et {pct(m.ia_top3)}{" "}
                pour BlackTurf. Le marché est donc aussi précis que nous, voire un peu plus. Notre
                avantage n&apos;est pas de mieux deviner l&apos;arrivée : à précision égale, nous
                désignons des chevaux plus chers, et miser 1 € Gagnant sur le favori du marché
                aurait rendu {pct(m.marche_favori_roi)} contre {pct(m.ia_favori_roi)} sur le nôtre.
                Les deux sont négatifs, et c&apos;est le prélèvement qui l&apos;impose.
              </p>
            )}

            {g.favori_roi !== null && g.favori_roi !== undefined && (
              <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-sm leading-relaxed text-brand-charcoal">
                <strong className="text-brand-dark">Ce que cela ne veut pas dire.</strong> Miser 1 €
                Gagnant sur le favori de l&apos;algorithme, sur ces{" "}
                {g.nb_favoris_evalues.toLocaleString("fr-FR")} courses, aurait rendu{" "}
                {pct(g.favori_roi)} — autrement dit une perte. Le PMU prélève environ 20 % des
                enjeux avant toute redistribution : le pari hippique est un jeu à somme négative,
                et mieux classer les chevaux que le marché ne suffit pas à le renverser. BlackTurf
                mesure sa valeur par l&apos;écart au classement du marché, jamais par un rendement
                promis.
              </p>
            )}
          </>
        ) : (
          <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
            Les chiffres détaillés sont affichés plus haut, dès qu&apos;ils sont chargés. Ils portent
            sur l&apos;intégralité des courses analysées depuis la mise en service, sans sélection :
            le pari hippique est un jeu à somme négative — le PMU prélève environ 20 % des enjeux
            avant redistribution — et BlackTurf publie ses périodes perdantes comme ses périodes
            gagnantes.
          </p>
        )}

        <nav className="mt-5 flex flex-wrap gap-2 text-[12.5px]">
          {[
            { href: "/programme", txt: "Programme PMU du jour" },
            { href: "/resultats", txt: "Arrivées et rapports du jour" },
            { href: "/guides/pari-de-valeur", txt: "Ce qu'est un pari de valeur" },
            { href: "/tarifs", txt: "Formules et tarifs" },
          ].map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 font-medium text-brand-charcoal transition-colors hover:border-brand-gold-deep hover:text-brand-gold-dark"
            >
              {l.txt}
            </Link>
          ))}
        </nav>
      </div>
    </section>
  );
}
