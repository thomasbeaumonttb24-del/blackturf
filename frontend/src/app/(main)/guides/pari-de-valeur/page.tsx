import type { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";
import Link from "next/link";
import { Target, TrendingUp } from "lucide-react";
import { SeoHero, Container, Section, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Le pari de valeur expliqué",
  description:
    "Qu'est-ce qu'un pari de valeur aux courses : probabilité réelle contre cote, espérance de gain, et pourquoi le favori paie rarement.",
  alternates: { canonical: "/guides/pari-de-valeur" },
  openGraph: {
    title: "Le pari de valeur expliqué",
    description: "Probabilité vs cote, espérance de gain, et pourquoi la valeur bat le favori sur la durée.",
    url: "https://blackturf.fr/guides/pari-de-valeur",
    type: "article",
    images: [OG_IMAGE],
  },
};

export default function GuideValeur() {
  const articleLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Le pari de valeur expliqué",
    description: metadata.description,
    author: { "@type": "Organization", name: "BlackTurf" },
    publisher: { "@type": "Organization", name: "BlackTurf", logo: { "@type": "ImageObject", url: "https://blackturf.fr/logo.png" } },
    mainEntityOfPage: "https://blackturf.fr/guides/pari-de-valeur",
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Guides", item: "https://blackturf.fr/guides" },
      { "@type": "ListItem", position: 2, name: "Pari de valeur", item: "https://blackturf.fr/guides/pari-de-valeur" },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(articleLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }} />

      <SeoHero
        eyebrow="Guide"
        title="Le pari de"
        accent="valeur expliqué"
        lead="Un pari de valeur n'est pas « le cheval qui va gagner ». C'est un cheval dont la probabilité réelle de l'emporter dépasse ce que sa cote laisse penser. Parier la valeur, c'est jouer les écarts entre le marché et la réalité."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Guides", href: "/guides" }, { label: "Pari de valeur" }]}
        chips={<><Chip tone="gold"><Target className="h-3 w-3" /> Stratégie</Chip><Chip>Espérance positive</Chip></>}
      />

      <Container>
        {/* Formule EV en highlight */}
        <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-6 text-center">
          <p className="text-xs font-semibold uppercase tracking-wider text-brand-gold-dark">La formule à retenir</p>
          <div className="mt-3 font-display text-2xl font-bold text-brand-dark sm:text-3xl">
            EV = <span className="text-gradient">probabilité × cote − 1</span>
          </div>
          <p className="mt-3 text-sm text-brand-charcoal">
            Espérance positive → le pari rapporte sur la durée. Négative → il perd.
          </p>
        </div>

        <Section title="Cote et probabilité implicite">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Une cote correspond à une probabilité implicite : <strong className="text-brand-dark">proba ≈ 1 / cote</strong>. Un cheval à 4,0 « vaut » environ 25 % de chances aux yeux du marché. Si votre estimation est qu&apos;il a en réalité 33 % de chances, il y a de la valeur.
          </p>
        </Section>

        <Section title="Deux exemples concrets">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-5">
              <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                <TrendingUp className="h-3 w-3" /> Value bet
              </div>
              <p className="mt-3 text-sm text-brand-charcoal">33 % de chances à une cote de <strong>4,0</strong></p>
              <div className="mt-2 font-display text-xl font-bold text-emerald-700">0,33 × 4,0 − 1 = +0,32</div>
              <p className="mt-1 text-xs text-brand-charcoal">+32 % d&apos;espérance : on joue.</p>
            </div>
            <div className="rounded-2xl border border-red-200 bg-red-50/50 p-5">
              <div className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-brand-red">
                Pas de valeur
              </div>
              <p className="mt-3 text-sm text-brand-charcoal">Le même cheval à une cote de <strong>2,5</strong></p>
              <div className="mt-2 font-display text-xl font-bold text-brand-red">0,33 × 2,5 − 1 = −0,18</div>
              <p className="mt-1 text-xs text-brand-charcoal">Espérance négative : on passe.</p>
            </div>
          </div>
        </Section>

        <Section title="Pourquoi pas simplement le favori ?">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Parce que le favori est, par définition, déjà cher : tout le monde le joue, sa cote s&apos;écrase, et l&apos;espérance fond. Sur la durée, suivre les favoris revient à payer le prélèvement du PMU (15 à 30 %) sans avantage. La valeur se trouve dans les chevaux que le marché sous-estime — voir aussi{" "}
            <Link href="/blog/favori-ou-outsider" className="font-medium text-brand-gold-dark underline">favori ou outsider ?</Link>
          </p>
        </Section>

        <Section title="Comment BlackTurf la détecte">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            BlackTurf estime la probabilité réelle de chaque cheval avec un modèle entraîné sur des dizaines de milliers de courses (XGBoost + LightGBM + CatBoost, 80+ critères), calibré après chaque journée. Il la compare à la cote PMU en direct et signale les écarts à espérance positive — les paris de valeur — avec un niveau de conviction. Aucune garantie de gain : un outil qui maximise les chances, honnêtement.
          </p>
        </Section>

        <Callout href="/programme" cta="Voir le programme">
          Voir les paris de valeur détectés aujourd&apos;hui, course par course.
        </Callout>
      </Container>
    </>
  );
}
