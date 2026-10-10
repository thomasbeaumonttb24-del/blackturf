import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check, Crown } from "lucide-react";
import { fetchTrackRecord } from "@/lib/seo";

/**
 * Page d'arrivée des réseaux sociaux (lien de la bio TikTok, Instagram, Facebook).
 *
 * Le visiteur arrive d'une vidéo qui parlait de courses, pas du site. Les vidéos ne
 * peuvent pas vendre (TikTok interdit la promotion des services de paris) : c'est cette
 * page qui convertit. Elle se lit comme une vidéo, en images et en chiffres, presque
 * sans texte : vrais écrans du site, chiffres mesurés, puis gratuit → Pass Jour → Expert.
 *
 * Hors index : page de campagne, son contenu double l'accueil et /tarifs.
 * Chiffres lus dans l'API, jamais écrits en dur ; un bloc disparaît plutôt que
 * d'afficher un zéro.
 */
export const revalidate = 900;

const TITLE = "Découvrir BlackTurf : chaque course PMU en chiffres";
const DESCRIPTION =
  "BlackTurf en 30 secondes : les chances de chaque cheval, le classement de l'algorithme et un plan de mise à ton budget.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/decouvrir" },
  robots: { index: false, follow: true },
};

const nb = (v: number) => v.toLocaleString("fr-FR");
const pct = (v: number) => `${v.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} %`;

const INSCRIPTION = `/inscription?suite=${encodeURIComponent("/programme")}`;

const ECRANS = [
  { src: "/img/decouvrir/synthese.webp", t: "La course en un coup d'œil", alt: "Synthèse d'une course : favori de l'algorithme à 50 %, accord des modèles 76/100" },
  { src: "/img/decouvrir/classement.webp", t: "Les chances de chaque cheval", alt: "Fiche partant : 50 % de chances de victoire, 78 % dans les 3 premiers, cote et cote juste" },
  { src: "/img/decouvrir/plan.webp", t: "Un plan à ton budget", alt: "Plan de mise de 10 € figé avant le départ, profils Prudent, Modéré, Risqué" },
];

const FORMULES = [
  { nom: "Gratuit", prix: "0 €", sous: "pour toujours", points: ["Programme + cotes en direct", "1 course analysée / jour", "Défi du mois"], cta: "Créer mon compte", href: INSCRIPTION, fort: false },
  { nom: "Pass Jour", prix: "5 €", sous: "24 h · sans abonnement", points: ["Tout débloqué 24 h", "Rien ne se renouvelle", "Parfait un jour de Quinté+"], cta: "Tester 24 h", href: "/tarifs#passes", fort: false },
  { nom: "Expert", prix: "19 €", sous: "/ mois · sans engagement", points: ["Toutes les courses, sans limite", "Paris de valeur en direct", "Assistant IA + alertes"], cta: "Passer Expert", href: "/tarifs", fort: true },
];

function Telephone({ src, alt, priority = false }: { src: string; alt: string; priority?: boolean }) {
  return (
    <div className="mx-auto w-[220px] shrink-0 rounded-[2.2rem] bg-stone-900 p-2 shadow-[0_30px_60px_-20px_rgba(0,0,0,.45)] ring-1 ring-stone-700 sm:w-[240px]">
      <div className="relative overflow-hidden rounded-[1.7rem] bg-white">
        <div className="absolute left-1/2 top-2 z-10 h-5 w-20 -translate-x-1/2 rounded-full bg-stone-900" aria-hidden />
        <Image src={src} alt={alt} width={560} height={774} priority={priority} className="h-auto w-full" />
      </div>
    </div>
  );
}

export default async function DecouvrirPage() {
  const tr = await fetchTrackRecord();
  const g = tr?.global;
  const mesure = g && g.nb_courses_analysees > 0 && g.accuracy_top3 != null && g.hasard_top3 != null;

  const chiffres = mesure
    ? [
        { v: nb(g.nb_courses_analysees), l: "courses analysées" },
        { v: pct(g.accuracy_top3), l: `n°1 de l'algo dans le top 3 (hasard ${pct(g.hasard_top3)})` },
        { v: "Chaque nuit", l: "le modèle réapprend" },
        { v: "100 %", l: "des résultats publiés" },
      ]
    : [];

  return (
    <div className="bg-[#fbf8f2]">
      {/* Accroche */}
      <section className="relative overflow-hidden bg-gradient-to-br from-stone-950 via-stone-900 to-emerald-950 text-white">
        <div className="mx-auto grid max-w-5xl items-center gap-10 px-4 py-12 sm:py-16 md:grid-cols-[1.1fr_1fr]">
          <div>
            <span className="inline-flex rounded-full bg-amber-400/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-amber-300 ring-1 ring-amber-400/30">
              Tu viens de nos vidéos ?
            </span>
            <h1 className="mt-5 font-display text-4xl font-bold leading-[1.05] tracking-tight sm:text-5xl">
              Chaque course PMU,
              <br />
              <span className="bg-gradient-to-r from-amber-200 to-amber-500 bg-clip-text text-transparent">en chiffres.</span>
            </h1>
            <p className="mt-4 max-w-md text-base text-stone-300">Les chances de chaque cheval. Un plan à ton budget. Tout vérifié.</p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <Link
                href={INSCRIPTION}
                className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-6 py-3.5 text-base font-bold text-stone-900 shadow-lg transition-transform hover:scale-[1.02]"
              >
                Essayer gratuitement <ArrowRight className="h-5 w-5" />
              </Link>
              <Link
                href="/tarifs"
                className="inline-flex items-center justify-center rounded-xl px-6 py-3.5 text-base font-semibold text-white ring-1 ring-white/25 hover:bg-white/10"
              >
                Voir les prix
              </Link>
            </div>
            <p className="mt-3 text-xs text-stone-400">Sans carte bancaire · 18 ans et plus</p>
          </div>
          <Telephone src={ECRANS[0].src} alt={ECRANS[0].alt} priority />
        </div>
      </section>

      {/* Chiffres clés */}
      {mesure && (
        <section className="border-b border-amber-100 bg-white">
          <div className="mx-auto grid max-w-5xl grid-cols-2 gap-px bg-amber-100 md:grid-cols-4">
            {chiffres.map((c) => (
              <div key={c.l} className="bg-white px-4 py-7 text-center">
                <div className="font-display text-3xl font-bold text-brand-dark sm:text-4xl">{c.v}</div>
                <div className="mt-1 text-xs leading-snug text-brand-charcoal sm:text-sm">{c.l}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Le site en 3 écrans */}
      <section className="mx-auto max-w-5xl px-4 py-14">
        <h2 className="text-center font-display text-2xl font-bold text-brand-dark sm:text-3xl">Le site en 3 écrans</h2>
        <div className="-mx-4 mt-8 flex snap-x snap-mandatory gap-6 overflow-x-auto px-4 pb-4 md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0">
          {ECRANS.map((e, i) => (
            <figure key={e.src} className="snap-center">
              <Telephone src={e.src} alt={e.alt} />
              <figcaption className="mt-4 flex items-center justify-center gap-2 font-display text-base font-semibold text-brand-dark">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-b from-amber-300 to-amber-500 text-sm font-bold text-stone-900">
                  {i + 1}
                </span>
                {e.t}
              </figcaption>
            </figure>
          ))}
        </div>
        <p className="mt-2 text-center text-xs text-brand-charcoal">Écrans réels d&apos;une course du 3 octobre 2026.</p>
      </section>

      {/* Formules */}
      <section className="mx-auto max-w-5xl px-4 pb-14">
        <h2 className="text-center font-display text-2xl font-bold text-brand-dark sm:text-3xl">Commence gratuit. Débloque tout quand tu veux.</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3 md:items-center">
          {FORMULES.map((f) => (
            <div
              key={f.nom}
              className={
                f.fort
                  ? "relative rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 p-6 text-white ring-2 ring-amber-400/70 md:scale-[1.04]"
                  : "rounded-3xl border border-gray-200 bg-white p-6"
              }
            >
              {f.fort && (
                <span className="absolute -top-3 left-6 inline-flex items-center gap-1 rounded-full bg-gradient-to-b from-amber-300 to-amber-500 px-3 py-1 text-xs font-bold text-stone-900">
                  <Crown className="h-3 w-3" /> Le plus complet
                </span>
              )}
              <div className={`text-sm font-semibold ${f.fort ? "text-amber-300" : "text-brand-gold-dark"}`}>{f.nom}</div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="font-display text-5xl font-extrabold">{f.prix}</span>
                <span className={`text-xs ${f.fort ? "text-stone-300" : "text-brand-charcoal"}`}>{f.sous}</span>
              </div>
              <ul className="mt-5 space-y-2">
                {f.points.map((p) => (
                  <li key={p} className="flex items-center gap-2 text-sm">
                    <Check className={`h-4 w-4 shrink-0 ${f.fort ? "text-amber-300" : "text-brand-gold-dark"}`} />
                    <span className={f.fort ? "text-stone-100" : "text-brand-charcoal"}>{p}</span>
                  </li>
                ))}
              </ul>
              <Link
                href={f.href}
                className={
                  f.fort
                    ? "mt-6 inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-3 text-sm font-bold text-stone-900"
                    : "mt-6 inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-amber-200 px-4 py-3 text-sm font-semibold text-brand-dark hover:bg-amber-50"
                }
              >
                {f.cta} <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          ))}
        </div>
        <p className="mt-6 text-center text-xs text-brand-charcoal">
          Aussi : Standard 12 €/mois, Pass Semaine 12 €, Pass Mois 24 €.{" "}
          <Link href="/tarifs" className="underline">Tous les prix</Link>
        </p>
      </section>

      <p className="mx-auto max-w-3xl px-4 pb-12 text-center text-[11px] leading-relaxed text-brand-charcoal">
        Jouer comporte des risques : endettement, dépendance… Appelez le 09 74 75 13 13 (appel non surtaxé).
        Réservé aux majeurs. BlackTurf est un outil d&apos;analyse : aucun gain n&apos;est garanti.
      </p>
    </div>
  );
}
