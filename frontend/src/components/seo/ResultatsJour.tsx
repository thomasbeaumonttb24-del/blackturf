import { CasaqueNumero } from "@/components/courses/identite-cheval";
import Link from "next/link";
import {
  fetchProgramme,
  fetchArriveesDuJour,
  fetchVerdictsDuJour,
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
  type SeoVerdict,

  jsonLd,
} from "@/lib/seo";
import { slugHippodrome } from "@/lib/hippodromes";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { SeoHero, Container, Section, Callout } from "@/components/seo/kit";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import { PreuvesRecentesCard } from "@/components/courses/insights";
import { BilanAlgoJour, VerdictAlgoLigne } from "@/components/seo/ComparaisonAlgo";

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

  /* Un seul appel pour toute la journée.
   *
   * Auparavant : un `Promise.all` sur `fetchResultats()`, soit une requête par course et
   * jusqu'à quatre-vingt-dix en parallèle. Le frontend sort par une seule IP et nginx
   * plafonne l'API à trente connexions simultanées par IP : tout ce qui dépassait
   * recevait un 503, que le fetch best-effort transformait en `null` — donc en arrivée
   * absente, sans message, sur une page qui annonçait pourtant le compte complet. Mesuré
   * le 2026-08-26 sur six journées : jusqu'à 14 arrivées affichées sur 62.
   *
   * `arrivees` vaut `null` si l'appel groupé échoue — cas distinct d'une journée
   * réellement sans arrivée, et signalé comme tel au lecteur plus bas. */
  const arrivees = await fetchArriveesDuJour(jour, estAujourdhui ? 120 : 21600);
  const avecArrivee: Array<readonly [SeoCourse, SeoResultats]> = terminees
    .map((c) => [c, arrivees?.[c.course_id]] as const)
    .filter((x): x is readonly [SeoCourse, SeoResultats] => !!x[1]?.classement?.length);
  const arriveesIndisponibles = arrivees === null;

  // Ce que l'algorithme avait annoncé, course par course — même appel groupé que
  // les arrivées, pour la même raison (une requête par course recréerait le 503
  // en cascade déjà corrigé sur `/seo/arrivees`). Best-effort : une panne de cet
  // appel n'empêche jamais d'afficher les arrivées elles-mêmes.
  const verdicts = await fetchVerdictsDuJour(jour, estAujourdhui ? 120 : 21600);
  const verdictsListe: SeoVerdict[] = verdicts ? Object.values(verdicts) : [];

  const quinte = avecArrivee.find(([c]) => c.est_quinte);
  const rapportsQuinte = quinte ? rapportsTries(quinte[1].rapports) : [];

  // Les hippodromes de la journée, dans l'ordre des réunions, sans doublon. Le slug est
  // nul pour les lieux qui n'ont pas de fiche — la majorité, les fiches couvrant les
  // seize hippodromes français principaux.
  const lieuxDuJour = [
    ...new Map(
      (prog?.reunions ?? [])
        .map((r) => titleCase(r.hippodrome))
        .filter(Boolean)
        .map((nom) => [nom, { nom, slug: slugHippodrome(nom) }]),
    ).values(),
  ];

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
        dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }}
      />
      {itemListJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(itemListJsonLd) }}
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
          arriveesIndisponibles
            ? // Ne jamais annoncer « aucune arrivée » quand on n'a pas pu les lire : la
              // page dirait le contraire de la vérité, et le dirait dans son titre.
              `Les arrivées du ${jourLong(jour)} n'ont pas pu être chargées. Réessayez dans un instant.`
            : avecArrivee.length
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
        {/* Les hippodromes du jour, liés à leur fiche.
         *
         * Le nom de l'hippodrome est déjà écrit sur chaque ligne d'arrivée, mais à
         * l'intérieur du lien vers la fiche course : on ne peut pas y imbriquer un second
         * lien. Cette ligne le fait une fois par réunion, avec une ancre qui nomme le
         * lieu. Elle donne aux seize fiches d'hippodrome un lien depuis une page explorée
         * tous les jours — mesuré le 2026-09-21, elles n'en avaient qu'un, depuis
         * `/hippodromes`, et sept d'entre elles n'avaient jamais été explorées. */}
        {lieuxDuJour.length > 0 && (
          <div className="mb-8">
            <p className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-stone-400">
              Hippodromes du jour
            </p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {lieuxDuJour.map(({ nom, slug }) => (
                <li key={nom}>
                  {slug ? (
                    <Link
                      href={`/hippodromes/${slug}`}
                      className="inline-block rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[12.5px] font-medium text-brand-gold-dark transition-colors hover:border-brand-gold-deep"
                    >
                      {nom}
                    </Link>
                  ) : (
                    <span className="inline-block rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[12.5px] text-stone-600">
                      {nom}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {quinte ? (
          <div className="mb-8">
            <Section title={`Arrivée du Quinté+ — ${titleCase(quinte[0].hippodrome_nom)}`}>
              <CarteArrivee
                course={quinte[0]}
                resultats={quinte[1]}
                verdict={verdicts?.[quinte[0].course_id]}
                rapportsMax={rapportsQuinte.length}
                vedette
              />
              {estAujourdhui && (
                <p className="mt-3 text-sm">
                  <Link href="/quinte-du-jour" className="font-medium text-brand-gold-dark hover:underline">
                    Détail complet du Quinté+ du jour
                  </Link>
                </p>
              )}
            </Section>
          </div>
        ) : null}

        <BilanAlgoJour verdicts={verdictsListe} nbCoursesJour={avecArrivee.length} />

        <Section title={`Toutes les arrivées du ${jourLong(jour)}`}>
          {avecArrivee.length ? (
            <ul className="grid gap-4 md:grid-cols-2 md:gap-5">
              {avecArrivee.map(([c, r]) => (
                <li key={c.course_id} className="min-w-0">
                  <CarteArrivee course={c} resultats={r} verdict={verdicts?.[c.course_id]} rapportsMax={6} />
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

/**
 * Une arrivée = une carte. Les cinq premiers sont sur UNE ligne, en colonnes égales
 * (place, numéro, casaque, nom) : l'ancienne liste en ligne laissait les chevaux
 * passer à la ligne au hasard de la longueur des noms, et l'œil ne retrouvait plus
 * l'ordre d'arrivée. Les rapports suivent en tuiles, le verdict de l'algo en pied.
 */
function CarteArrivee({
  course: c,
  resultats: r,
  verdict,
  rapportsMax,
  vedette = false,
}: {
  course: SeoCourse;
  resultats: SeoResultats;
  verdict?: SeoVerdict;
  rapportsMax: number;
  vedette?: boolean;
}) {
  const top = r.classement!.slice(0, 5);
  const rapports = rapportsTries(r.rapports).slice(0, rapportsMax);
  const typeCourse = c.est_quinte ? "Quinté+" : c.est_quarte ? "Quarté+" : null;

  return (
    <article
      className={`flex h-full flex-col overflow-hidden rounded-2xl border bg-white shadow-[0_1px_3px_rgba(17,24,39,0.05)] ${
        vedette ? "border-amber-200" : "border-stone-200"
      }`}
    >
      {/* En-tête : repère R/C + heure, puis la course */}
      <header className="px-4 pb-3 pt-4 sm:px-5">
        <div className="flex items-center gap-2 text-[11.5px] font-semibold text-stone-500">
          <span className="rounded-md bg-brand-dark px-1.5 py-0.5 font-display text-[11px] font-bold tracking-wide text-white">
            {codeReunionCourse(c.course_id)}
          </span>
          <span className="tabular-nums">{heureParis(c.date_heure)}</span>
          {typeCourse && (
            <span className="rounded-md bg-amber-100 px-1.5 py-0.5 text-[10.5px] font-bold text-amber-800">
              {typeCourse}
            </span>
          )}
        </div>
        <Link
          href={`/courses/${c.course_id}`}
          className="mt-2 block font-display text-[15px] font-semibold leading-snug text-brand-dark hover:text-brand-gold-dark"
        >
          {titleCase(c.hippodrome_nom)}
          <span className="font-normal text-stone-400"> — </span>
          <span className="font-medium">{titleCase(c.nom ?? "")}</span>
        </Link>
        <p className="mt-1 text-[12px] text-stone-500">
          {disciplineLabel(c.discipline)} · {c.distance} m · {c.nb_partants} partants
        </p>
      </header>

      {/* Arrivée : cinq colonnes égales, toujours sur une ligne */}
      <ol
        aria-label="Arrivée"
        className="grid grid-cols-5 gap-1 border-y border-stone-100 bg-stone-50/70 px-2 py-3 sm:gap-2 sm:px-3"
      >
        {top.map((l, i) => (
          <li
            key={l.numero}
            className={`flex min-w-0 flex-col items-center gap-1.5 rounded-xl px-0.5 py-2 text-center ${
              i === 0 ? "bg-amber-50 ring-1 ring-amber-200" : ""
            }`}
          >
            <span
              className={`text-[11px] font-bold tabular-nums ${
                i === 0 ? "text-amber-700" : "text-stone-400"
              }`}
            >
              {l.position === 1 ? "1er" : `${l.position}e`}
            </span>
            <CasaqueNumero numero={l.numero} courseId={c.course_id} vertical />
            <span
              className="line-clamp-2 w-full break-words px-0.5 text-[10.5px] font-medium leading-tight text-stone-700 sm:text-[11.5px]"
              title={titleCase(l.nom)}
            >
              {titleCase(l.nom)}
            </span>
          </li>
        ))}
      </ol>

      {/* Rapports PMU pour 1 € */}
      {rapports.length > 0 && (
        <div className="px-4 pt-3 sm:px-5">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-stone-400">
            Rapports pour 1 €
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {rapports.map(([code, val]) => (
              <div key={code} className="min-w-0 rounded-lg border border-stone-100 bg-stone-50 px-2.5 py-1.5">
                <dt className="truncate text-[10.5px] text-stone-500">{libellePari(code)}</dt>
                <dd className="font-display text-[14px] font-bold tabular-nums text-brand-dark">
                  {formatRapport(val)} €
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Verdict de l'algo, poussé en pied pour aligner les cartes voisines */}
      <footer className="mt-auto px-4 pb-4 pt-2 sm:px-5">
        {verdict ? (
          <div className="border-t border-stone-100 pt-1.5">
            <VerdictAlgoLigne v={verdict} courseId={c.course_id} />
          </div>
        ) : (
          <Link
            href={`/courses/${c.course_id}`}
            className="mt-1.5 inline-block text-[11.5px] font-medium text-brand-gold-dark hover:underline"
          >
            Voir le détail →
          </Link>
        )}
      </footer>
    </article>
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
