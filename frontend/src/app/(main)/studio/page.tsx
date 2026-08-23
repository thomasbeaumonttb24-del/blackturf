import type { Metadata } from "next";
import { jourParis, jourLong } from "@/lib/seo";
import { publicationsDuJour } from "@/lib/visuels-legendes";
import { Container, SeoHero, Section } from "@/components/seo/kit";
import { BoutonCopier } from "@/components/studio/BoutonCopier";

export const revalidate = 300;

// Page de travail interne : elle n'a rien à faire dans un index de recherche.
export const metadata: Metadata = {
  title: "Studio — visuels et légendes du jour",
  robots: { index: false, follow: false },
};

// Le libellé du moment de publication n'a de sens qu'ici : le service de publication du
// backend, lui, connaît son propre horaire.
const QUAND: Record<string, string> = {
  matin: "À publier vers 9 h, une fois le support connu.",
  soir: "À publier dès les rapports publiés, généralement 15 à 30 min après la course.",
};

export default async function StudioPage() {
  const jour = jourParis();
  const visuels = await publicationsDuJour();

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
            <p className="text-sm text-brand-charcoal/70">{QUAND[v.cle]}</p>

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
