import Link from "next/link";
import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  jourLong,
  jourCourt,
  jourCourtAnnee,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  PREMIER_JOUR_ARCHIVE,
  type SeoCourse,
  type SeoResultats,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { SeoHero, Container, Section, Callout } from "@/components/seo/kit";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import { PreuvesRecentesCard } from "@/components/courses/insights";

/**
 * Page « arrivées et rapports » d'une journée PMU.
 *
 * Sert à la fois /resultats (aujourd'hui) et /resultats/<AAAA-MM-JJ> (archives). Chaque
 * journée passée reste une page utile et unique — l'arrivée et les rapports d'une course
 * ne changent plus jamais — ce qui donne au site un stock de contenu qui ne se périme pas,
 * là où le programme du jour, lui, est remplacé chaque matin.
 */
export async function ResultatsJour({ jour }: { jour: string }) {
  const estAujourdhui = jour === jourParis();
  const prog = await fetchProgramme(jour);

  const terminees: SeoCourse[] = (prog?.reunions ?? [])
    .flatMap((r) => r.courses ?? [])
    .filter((c) => c.statut === "termine")
    .sort((a, b) => a.date_heure.localeCompare(b.date_heure));

  const resultats = await Promise.all(
    terminees.map(async (c) => [c, await fetchResultats(c.course_id)] as const),
  );
  const avecArrivee = resultats.filter(
    (x): x is readonly [SeoCourse, SeoResultats] => !!x[1]?.classement?.length,
  );

  const quinte = avecArrivee.find(([c]) => c.est_quinte);
  const rapportsQuinte = quinte ? rapportsTries(quinte[1].rapports) : [];

  const veille = decalerJour(jour, -1);
  const lendemain = decalerJour(jour, 1);
  const lendemainDisponible = lendemain <= jourParis();

  /* Données structurées. Cette page était la plus riche du site — jusqu'à cinquante et
   * une arrivées avec leurs rapports — et la seule à n'émettre aucun balisage propre :
   * elle n'héritait que de l'`Organization` et du `WebSite` globaux. Un fil d'Ariane et
   * la liste ordonnée des courses disent à Google ce que la page contient réellement, et
   * lui donnent les liens vers les fiches détaillées.
   *
   * Chaque élément listé correspond à un lien visible plus haut : rien n'est balisé qui
   * ne soit affiché. */
  const urlPage = estAujourdhui
    ? "https://blackturf.fr/resultats"
    : `https://blackturf.fr/resultats/${jour}`;

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
      { "@type": "ListItem", position: 2, name: "Résultats", item: "https://blackturf.fr/resultats" },
      ...(estAujourdhui
        ? []
        : [
            {
              "@type": "ListItem",
              position: 3,
              name: `Résultats du ${jourCourtAnnee(jour)}`,
              item: urlPage,
            },
          ]),
    ],
  };

  const itemListJsonLd = avecArrivee.length
    ? {
        "@context": "https://schema.org",
        "@type": "ItemList",
        name: `Arrivées PMU du ${jourLong(jour)}`,
        numberOfItems: avecArrivee.length,
        // `position` compte sur la LISTE ENTIÈRE. Numéroter par sous-groupe produit des
        // positions répétées, ce que schema.org n'admet pas dans une ItemList.
        itemListElement: avecArrivee.map(([c], i) => ({
          "@type": "ListItem",
          position: i + 1,
          url: `https://blackturf.fr/courses/${c.course_id}`,
          name: `${codeReunionCourse(c.course_id)} ${titleCase(c.hippodrome_nom)} — ${titleCase(
            c.nom ?? "",
          )}`.trim(),
        })),
      }
    : null;

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
      />
      {itemListJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListJsonLd) }}
        />
      )}

      <SeoHero
        eyebrow="Arrivées officielles"
        breadcrumbs={[
          { label: "Accueil", href: "/" },
          { label: "Résultats", href: "/resultats" },
          ...(estAujourdhui ? [] : [{ label: jourCourt(jour) }]),
        ]}
        title={`Résultats PMU du ${jourCourt(jour)}`}
        lead={
          avecArrivee.length
            ? `${avecArrivee.length} arrivées publiées sur les ${prog?.nb_courses ?? 0} courses du ${jourLong(
                jour,
              )}. Rapports officiels PMU pour 1 € de mise.`
            : `Aucune arrivée publiée pour le ${jourLong(jour)}.${
                estAujourdhui
                  ? " Les rapports paraissent quelques minutes après chaque course."
                  : ""
              }`
        }
      />

      <Container>
        {quinte ? (
          <Section title={`Arrivée du Quinté+ — ${titleCase(quinte[0].hippodrome_nom)}`}>
            <p className="text-sm text-brand-charcoal">
              Arrivée :{" "}
              <strong className="tabular-nums">
                {quinte[1].classement!.slice(0, 5).map((l) => l.numero).join(" - ")}
              </strong>{" "}
              — {titleCase(quinte[1].classement![0].nom)} l&apos;emporte.
            </p>
            {rapportsQuinte.length ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[380px] text-sm">
                  <tbody>
                    {rapportsQuinte.map(([code, val]) => (
                      <tr key={code} className="border-b border-amber-50">
                        <td className="py-2 pr-3 text-brand-charcoal">{libellePari(code)}</td>
                        <td className="py-2 text-right font-semibold tabular-nums text-brand-dark">
                          {formatRapport(val)} €
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {estAujourdhui && (
              <p className="mt-3 text-sm">
                <Link href="/quinte-du-jour" className="font-medium text-brand-gold-dark hover:underline">
                  Détail complet du Quinté+ du jour
                </Link>
              </p>
            )}
          </Section>
        ) : null}

        <Section title={`Toutes les arrivées du ${jourLong(jour)}`}>
          {avecArrivee.length ? (
            <ul className="space-y-4">
              {avecArrivee.map(([c, r]) => (
                <li key={c.course_id} className="border-b border-amber-50 pb-4 last:border-0">
                  <Link
                    href={`/courses/${c.course_id}`}
                    className="font-display text-[15px] font-semibold text-brand-dark hover:text-brand-gold-dark"
                  >
                    {codeReunionCourse(c.course_id)} · {titleCase(c.hippodrome_nom)} —{" "}
                    {titleCase(c.nom ?? "")}
                  </Link>
                  <div className="mt-0.5 text-[12px] text-brand-charcoal">
                    {heureParis(c.date_heure)} · {disciplineLabel(c.discipline)} · {c.distance} m ·{" "}
                    {c.nb_partants} partants
                    {c.est_quinte ? " · Quinté+" : c.est_quarte ? " · Quarté+" : ""}
                  </div>
                  <div className="mt-1.5 text-sm text-brand-charcoal">
                    Arrivée :{" "}
                    <strong className="tabular-nums">
                      {r.classement!.slice(0, 5).map((l) => l.numero).join(" - ")}
                    </strong>{" "}
                    <span className="text-brand-charcoal">
                      ({r.classement!.slice(0, 3).map((l) => titleCase(l.nom)).join(", ")})
                    </span>
                  </div>
                  {rapportsTries(r.rapports).length ? (
                    <div className="mt-1 text-[12.5px] text-brand-charcoal">
                      {rapportsTries(r.rapports)
                        .slice(0, 5)
                        .map(([code, val]) => `${libellePari(code)} ${formatRapport(val)} €`)
                        .join(" · ")}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-brand-charcoal">
              Aucune arrivée à afficher pour cette journée. Voir le{" "}
              <Link href="/programme" className="font-medium text-brand-gold-dark hover:underline">
                programme du jour
              </Link>
              .
            </p>
          )}
        </Section>

        {/* Ce que le modèle avait dit sur les dernières courses courues. Réservé à
            la page du JOUR : sur une archive, « les dernières courses » ne sont pas
            celles que le lecteur regarde, et le bloc mentirait par juxtaposition. */}
        {estAujourdhui && (
          <div className="mt-8">
            <PreuvesRecentesCard />
          </div>
        )}

        <Section title="Autres journées">
          <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
            <Link href={`/resultats/${veille}`} className="font-medium text-brand-gold-dark hover:underline">
              ← Résultats du {jourCourt(veille)}
            </Link>
            {!estAujourdhui && (
              <Link href="/resultats" className="font-medium text-brand-gold-dark hover:underline">
                Résultats d&apos;aujourd&apos;hui
              </Link>
            )}
            {!estAujourdhui && lendemainDisponible && (
              <Link
                href={lendemain === jourParis() ? "/resultats" : `/resultats/${lendemain}`}
                className="font-medium text-brand-gold-dark hover:underline"
              >
                Résultats du {jourCourt(lendemain)} →
              </Link>
            )}
          </nav>

          {/* Les quatorze journées précédentes en accès direct, plus l'entrée des
              archives. Auparavant cette section n'offrait que « journée précédente » :
              atteindre le mois de septembre 2025 demandait de suivre la chaîne jour
              après jour, ce qu'aucun robot ne fait — l'historique entier du site était
              donc publié sans être explorable. */}
          <ul className="mt-4 flex flex-wrap gap-2">
            {joursPrecedents(jour, 14).map((j) => (
              <li key={j}>
                <Link
                  href={`/resultats/${j}`}
                  className="inline-block rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[13px] text-brand-charcoal transition-colors hover:border-brand-gold-deep hover:text-brand-gold-dark"
                >
                  {jourCourt(j)}
                </Link>
              </li>
            ))}
            <li>
              <Link
                href="/resultats/archives"
                className="inline-block rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[13px] font-medium text-brand-gold-dark transition-colors hover:border-brand-gold-deep"
              >
                Toutes les archives →
              </Link>
            </li>
          </ul>
        </Section>

        <div className="mt-10">
          <NewsletterForm
            source={estAujourdhui ? "resultats" : "resultats-archive"}
            titre="Recevoir le bilan de la semaine"
            accroche="Les rapports d'aujourd'hui ne disent pas ce que paiera demain. Chaque lundi, le bilan chiffré de la semaine écoulée — gains comme pertes."
          />
        </div>

        <Callout href="/programme" cta="Voir le programme">
          Les rapports d&apos;une course passée disent ce qu&apos;elle a payé — pas ce que paiera la
          suivante. BlackTurf note chaque pronostic aux rapports réels du PMU et publie le bilan,
          gains comme pertes.
        </Callout>
      </Container>
    </>
  );
}

/** "2026-08-23" + n jours → "2026-08-2x" (arithmétique en UTC midi, sans dérive de fuseau). */
export function decalerJour(jour: string, n: number): string {
  const d = new Date(`${jour}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Les `n` journées qui précèdent `jour`, bornées à la fenêtre réellement couverte. */
function joursPrecedents(jour: string, n: number): string[] {
  const out: string[] = [];
  for (let i = 1; i <= n; i++) {
    const j = decalerJour(jour, -i);
    if (j < PREMIER_JOUR_ARCHIVE) break;
    out.push(j);
  }
  return out;
}
