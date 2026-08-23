import type { Metadata } from "next";
import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  jourLong,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  type SeoCourse,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";
import { Container, SeoHero, Section } from "@/components/seo/kit";
import { BoutonCopier } from "@/components/studio/BoutonCopier";

export const revalidate = 300;

// Page de travail interne : elle n'a rien à faire dans un index de recherche.
export const metadata: Metadata = {
  title: "Studio — visuels et légendes du jour",
  robots: { index: false, follow: false },
};

async function quinteDuJour(jour: string): Promise<SeoCourse | null> {
  const prog = await fetchProgramme(jour);
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) return c;
  }
  return null;
}

export default async function StudioPage() {
  const jour = jourParis();
  const quinte = await quinteDuJour(jour);
  const resultats = quinte ? await fetchResultats(quinte.course_id) : null;
  const classement = resultats?.classement?.slice(0, 5) ?? [];
  const rapports = rapportsTries(resultats?.rapports).slice(0, 4);

  // ─── Légende du matin ───────────────────────────────────────────────────────
  const legendeMatin = quinte
    ? [
        `Quinté+ du jour — ${titleCase(quinte.hippodrome_nom)}.`,
        "",
        `${codeReunionCourse(quinte.course_id)} · ${disciplineLabel(quinte.discipline)} · ${
          quinte.distance
        } m · ${quinte.nb_partants} partants · départ ${heureParis(quinte.date_heure)}.`,
        "",
        "Partants, cotes comparées et probabilité calculée pour chaque cheval :",
        "blackturf.fr/quinte-du-jour",
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n")
    : [
        "Le support du Quinté+ n'est pas encore publié — le PMU le désigne la veille au soir.",
        "",
        "Le programme complet du jour est en ligne : blackturf.fr/programme",
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n");

  // ─── Légende du soir ────────────────────────────────────────────────────────
  const legendeSoir = classement.length
    ? [
        `Arrivée du Quinté+ — ${titleCase(quinte!.hippodrome_nom)}.`,
        "",
        classement.map((l) => l.numero).join(" - "),
        "",
        ...classement.map((l) => `${l.position}. n°${l.numero} ${titleCase(l.nom)}`),
        "",
        ...(rapports.length
          ? ["Rapports officiels pour 1 € :", rapports.map(([c, v]) => `${libellePari(c)} ${formatRapport(v)} €`).join(" · "), ""]
          : []),
        "Toutes les arrivées et tous les rapports du jour : blackturf.fr/resultats",
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n")
    : "L'arrivée n'est pas encore publiée. Cette légende se remplit seule dès que le PMU publie les rapports.";

  const visuels = [
    {
      titre: "Post du matin — Quinté+ du jour",
      quand: "À publier vers 9 h, une fois le support connu.",
      image: "/visuels/quinte",
      fichier: `blackturf-quinte-${jour}.png`,
      legende: legendeMatin,
      pret: Boolean(quinte),
    },
    {
      titre: "Post du soir — arrivée et rapports",
      quand: "À publier dès les rapports publiés, généralement 15 à 30 min après la course.",
      image: "/visuels/arrivee",
      fichier: `blackturf-arrivee-${jour}.png`,
      legende: legendeSoir,
      pret: classement.length > 0,
    },
  ];

  return (
    <>
      <SeoHero
        eyebrow="Interne"
        title="Studio"
        accent={jourLong(jour)}
        lead="Les visuels et les légendes du jour, assemblés sur les données réelles. Rien n'est saisi à la main, donc rien n'y est faux : il n'y a qu'à télécharger et publier."
      />

      <Container>
        {visuels.map((v) => (
          <Section key={v.titre} title={v.titre}>
            <p className="text-sm text-brand-charcoal/70">{v.quand}</p>

            {!v.pret && (
              <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                Les données ne sont pas encore disponibles. Le visuel se régénère seul :
                rechargez cette page plus tard.
              </p>
            )}

            <div className="mt-4 grid gap-6 lg:grid-cols-[320px_1fr]">
              <div className="flex flex-col gap-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={v.image}
                  alt={v.titre}
                  width={320}
                  height={320}
                  className="w-full rounded-xl border border-amber-100 bg-brand-dark"
                />
                <a
                  href={v.image}
                  download={v.fichier}
                  className="inline-flex items-center justify-center rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-gray-800"
                >
                  Télécharger le visuel
                </a>
              </div>

              <div className="flex flex-col gap-3">
                <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-amber-100 bg-white p-4 font-sans text-[13.5px] leading-relaxed text-brand-charcoal">
                  {v.legende}
                </pre>
                <BoutonCopier texte={v.legende} />
              </div>
            </div>
          </Section>
        ))}

        <Section title="Avant de publier">
          <ul className="space-y-2 text-sm leading-relaxed text-brand-charcoal/85">
            <li>
              Les visuels ne portent <strong>aucun pronostic et aucun chiffre de gain</strong>.
              Une image circule hors de son contexte : elle ne doit jamais pouvoir se lire comme
              une promesse.
            </li>
            <li>
              La mention de jeu responsable est déjà dans chaque légende et sur chaque visuel.
              Ne la retirez pas : les plateformes sanctionnent son absence avant l&apos;ANJ.
            </li>
            <li>
              Le format est un carré 1080 × 1080, qui passe en fil Instagram, en aperçu Facebook
              et sur X sans recadrage.
            </li>
          </ul>
        </Section>
      </Container>
    </>
  );
}
