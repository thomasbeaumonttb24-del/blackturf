import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight, Shield, Trophy, ChevronRight, AlertTriangle, ChevronDown,
} from "lucide-react";
import { PerformancesBento } from "@/components/home/PerformancesBento";
import { EtapesFonctionnement } from "@/components/home/EtapesFonctionnement";
import { Button } from "@/components/ui/button";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { BottomNav } from "@/components/layout/BottomNav";
import { ScrollReveal } from "@/components/ui/ScrollReveal";
import { LiveTicker } from "@/components/ui/LiveTicker";
import { LivePalmares } from "@/components/home/LivePalmares";
import { OutsidersDuJour } from "@/components/outsiders/Outsiders";
import { DefiBandeau } from "@/components/defi/DefiBandeau";
import { DefiClassementLive } from "@/components/defi/DefiClassementLive";
import { DefiConcept } from "@/components/defi/DefiConcept";
import { HeroStats } from "@/components/home/HeroStats";
import { fetchPalmaresPublic, ogBase, twitterBase } from "@/lib/seo";
import {
  apiServeurOrigine,
  initServeur,
  leverSiTransitoire,
  relancerSiTransitoire,
} from "@/lib/apiServeur";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import { OutilsEnEcrans } from "@/components/vitrine/OutilsEnEcrans";
import { FormulesSimples } from "@/components/vitrine/FormulesSimples";

// Le canonical n'est plus hérité de la racine (il y désignait "/" pour TOUTES les pages) :
// l'accueil déclare donc le sien explicitement.
const TITRE_ACCUEIL = "BlackTurf — pronostic PMU et Quinté+ du jour par IA";
const DESCRIPTION_ACCUEIL =
  "Programme PMU analysé par IA : une probabilité par cheval et un plan de mise ajusté à votre budget. Pronostics notés aux rapports réels du PMU.";

export const metadata: Metadata = {
  // « pronostic PMU » et « Quinté+ » : les deux requêtes les plus tapées sur ce créneau,
  // absentes jusqu'ici du titre de l'accueil (hérité du titre par défaut).
  title: TITRE_ACCUEIL,
  alternates: { canonical: "/" },
  // Le titre partagé suit celui de la page (le gabarit du layout en portait un autre).
  openGraph: ogBase({ title: TITRE_ACCUEIL, description: DESCRIPTION_ACCUEIL, url: "/" }),
  twitter: twitterBase({ title: TITRE_ACCUEIL, description: DESCRIPTION_ACCUEIL }),
};

const numOf = (x: unknown): number | null =>
  typeof x === "number" && !Number.isNaN(x) ? x : null;

interface TrackRecord {
  accuracy_top1: number | null;
  accuracy_top3: number | null;
  favori_place_rate: number | null;
  favori_win_rate: number | null;
  // Rendement RÉEL de 1 € Gagnant sur notre favori : négatif, et publié tel quel.
  favori_roi: number | null;
  nb_courses: number | null;
  mesure_depuis: string | null;
  hasard_top3: number | null;
  hasard_top1: number | null;
  /**
   * Le repère publié est le HASARD, et lui seul.
   *
   * L'accueil a porté un temps une comparaison au classement par la cote. Elle
   * était juste et elle ne servait à rien ici : sur les mêmes courses le marché
   * est aussi précis que nous, la page d'accueil passait donc son espace à
   * expliquer en quoi nous ne sommes pas meilleurs, et finissait sur deux
   * rendements négatifs. Ce n'est pas le rôle d'une page qui doit donner envie
   * d'essayer le produit. La comparaison reste mesurable côté API (`marche`),
   * simplement elle n'est plus affichée — décision produit du 2026-09-08.
   *
   * Le hasard, lui, est le repère qui dit ce que vaut le classement : `hasard_top3`
   * et `hasard_top1` ne sont pas des constantes posées à la main, ce sont les
   * espérances d'un tirage au sort sur le CHAMP RÉEL de chaque course. Le facteur
   * qu'on en tire est donc une vraie mesure, pas un effet de manche.
   */
  by_discipline: Array<{ discipline: string; nb_courses: number; accuracy_top3: number }>;
  by_day: Array<{ jour: string; accuracy_top3: number; nb_predictions: number }>;
}

// Questions qui bloquent réellement une inscription — la deuxième répond « non »
// à « est-ce que je vais gagner ». Une FAQ qui ne dit que du bien ne rassure
// personne, et le balisage FAQPage exige de toute façon le texte affiché.
function buildFaq(tr: TrackRecord | null): Array<{ q: string; r: string }> {
  const pc = (x: number | null, d = 1) => (x == null ? null : `${x.toFixed(d).replace(".", ",")} %`);
  const top3 = pc(tr?.accuracy_top3 ?? null);
  // Repère publié : le hasard, calculé sur le champ réel de chaque course.
  const hasard3 = pc(tr?.hasard_top3 ?? null, 0);
  const nb = tr?.nb_courses ? tr.nb_courses.toLocaleString("fr-FR") : null;
  return [
    {
      q: "Concrètement, que fait BlackTurf ?",
      r: "Nous analysons chaque course du programme PMU avant le départ : plus de 80 critères par cheval (forme, terrain, distance, jockey, mouvements de cote…), une probabilité pour chaque partant, puis un plan de mise calculé selon votre budget et votre tolérance au risque. Vous gardez la main : vous pariez où vous voulez, et nous ne prenons aucune commission sur vos gains.",
    },
    {
      q: "Est-ce que je vais gagner de l'argent ?",
      r: `Personne ne peut vous le garantir, et nous ne le ferons pas : le pari hippique reste soumis au prélèvement de l'opérateur et au hasard. Ce que nous publions, c'est la qualité de l'analyse${top3 ? ` — le gagnant figure dans notre Top-3 sur ${top3} des courses${hasard3 ? `, là où un tirage au sort sur le même champ n'y arriverait que ${hasard3} du temps` : ""}` : ""}, et le détail de chaque pari réglé, gagnant comme perdant.`,
    },
    {
      q: "Combien de temps ça me prend ?",
      r: "Le temps de lire une fiche. Quand vous arrivez, la course est déjà analysée : vous choisissez la course, vous entrez votre mise, le plan s'affiche. Les alertes préviennent quand un pari de valeur apparaît — pas besoin de surveiller le programme toute la journée.",
    },
    {
      q: "Quelle IA utilisez-vous ? Est-ce ChatGPT ?",
      r: "Non. ChatGPT et les agents conversationnels du même type produisent du texte : ils n'ont ni les partants du jour, ni les cotes, ni aucune mesure de leur propre justesse, et fabriquent des chiffres plausibles quand la donnée leur manque. BlackTurf fait tourner un modèle d'apprentissage supervisé entraîné sur l'historique réel des courses PMU, réentraîné chaque nuit sur les arrivées de la veille. Il ne rédige pas un avis : il sort une probabilité par cheval, dont l'erreur est mesurée course après course.",
    },
    {
      q: "D'où viennent les données ?",
      r: "Du programme officiel PMU (partants, cotes, arrivées, rapports), complété par plusieurs sources de cotes pour repérer les écarts de marché. Les résultats qui servent à noter nos pronostics sont les rapports PMU publiés — jamais une estimation maison.",
    },
    {
      q: "Vos statistiques sont-elles vérifiables ?",
      r: `Oui. Le palmarès est public : chaque pari gagné y figure avec sa course et son rapport officiel, à côté du nombre total de courses réglées — sans ce dénominateur, n'afficher que les gagnants n'aurait aucune valeur.${nb ? ` Les taux publiés portent sur ${nb} courses.` : ""}`,
    },
    {
      q: "Sur quelles courses ça fonctionne ?",
      r: "Sur toutes les disciplines du programme : trot attelé, trot monté, plat et obstacle. La précision n'est pas la même partout, c'est pourquoi nous la publions discipline par discipline plutôt que sous la forme d'un chiffre unique.",
    },
    {
      q: "Puis-je annuler ?",
      r: "L'abonnement se résilie à tout moment depuis votre compte, en deux clics. Les pass Jour, Semaine et Mois n'ont rien à annuler : paiement unique, sans renouvellement, l'accès se coupe seul à la fin.",
    },
  ];
}

async function fetchTrackRecord(): Promise<TrackRecord | null> {
  // Lecture serveur (cf. lib/apiServeur.ts) : réseau Docker + en-tête interne en prod.
  const base = apiServeurOrigine("http://localhost:8000");
  try {
    // 60 s, comme /track-record (`revalidate` de son layout). À 3 600 s, l'accueil
    // gardait pendant une heure les chiffres figés au build alors que le palmarès
    // affichait déjà les nouveaux : constaté en prod le 2026-09-09, juste après le
    // correctif des disqualifiés — 31,8 % ici contre 28,6 % là-bas, pour la même
    // phrase. L'API sert ce calcul depuis son propre cache Redis, le raccourcir ne
    // coûte donc rien à la base. L'API recalcule dans la minute qui suit chaque
    // course intégrée : garder la page plus longtemps annulerait ce gain.
    const url = `${base}/api/v1/stats/track-record`;
    const res = await fetch(url, initServeur({ next: { revalidate: 60 } }));
    // 429/5xx : lever plutôt que rendre un hero vide que l'ISR garderait en cache —
    // la revalidation échoue et la dernière bonne page reste servie.
    leverSiTransitoire(res, url);
    if (!res.ok) return null;
    const d = await res.json();
    const g = d?.global ?? {};
    const byDisc = Array.isArray(d?.by_discipline) ? d.by_discipline : [];
    const byDay = Array.isArray(d?.by_day) ? d.by_day : [];
    return {
      accuracy_top1: numOf(g.accuracy_top1),
      accuracy_top3: numOf(g.accuracy_top3),
      favori_place_rate: numOf(g.favori_place_rate),
      favori_win_rate: numOf(g.favori_win_rate),
      favori_roi: numOf(g.favori_roi),
      nb_courses: numOf(g.nb_courses_analysees),
      mesure_depuis: typeof g.mesure_depuis === "string" ? g.mesure_depuis : null,
      hasard_top3: numOf(g.hasard_top3),
      hasard_top1: numOf(g.hasard_top1),
      by_discipline: byDisc
        .filter((x: Record<string, unknown>) => numOf(x?.nb_courses) && (x.nb_courses as number) >= 10 && numOf(x?.accuracy_top3))
        .map((x: Record<string, unknown>) => ({ discipline: String(x.discipline ?? "autre"), nb_courses: x.nb_courses as number, accuracy_top3: x.accuracy_top3 as number }))
        .sort((a: { nb_courses: number }, b: { nb_courses: number }) => b.nb_courses - a.nb_courses),
      by_day: byDay
        .filter((x: Record<string, unknown>) => numOf(x?.nb_predictions) && (x.nb_predictions as number) > 0)
        .map((x: Record<string, unknown>) => ({ jour: String(x.jour ?? ""), accuracy_top3: numOf(x.accuracy_top3) ?? 0, nb_predictions: x.nb_predictions as number })),
    };
  } catch (e) {
    relancerSiTransitoire(e);
    return null;
  }
}

/**
 * Ne garde du palmarès que ce que l'accueil affiche (bandeau : 12 paris ; section :
 * 3 records + 6 derniers) : la réponse complète (50 + 30 paris) passerait telle
 * quelle dans le HTML, deux fois.
 */
function allegerPalmares(p: Record<string, unknown> | null) {
  if (!p) return null;
  const liste = (x: unknown) => (Array.isArray(x) ? x : []);
  return {
    gagnants: liste(p.gagnants).slice(0, 12),
    top_gains: liste(p.top_gains).slice(0, 12),
    nb_paris_gagnes: p.nb_paris_gagnes,
    nb_courses_gagnantes: p.nb_courses_gagnantes,
    nb_courses_reglees: p.nb_courses_reglees,
    updated_at: p.updated_at,
  };
}

export default async function HomePage() {
  // Palmarès lu en parallèle : le bandeau défilant et la section « Palmarès en
  // direct » sont servis remplis, au lieu d'apparaître après coup (bandeau qui
  // surgit et pousse la page, section vide puis remplie d'un coup).
  const [tr, palmaresBrut] = await Promise.all([fetchTrackRecord(), fetchPalmaresPublic()]);
  const palmares = allegerPalmares(palmaresBrut);
  const FAQ = buildFaq(tr);

  return (
    // pb mobile = hauteur de la BottomNav + safe-area : sans elle, le bas du pied de page
    // passerait sous la barre sur téléphone.
    <div className="flex flex-col min-h-screen bg-brand-warm pb-[calc(68px+env(safe-area-inset-bottom))] md:pb-0">
      {/* L'accueil n'est PAS dans le groupe (main) : il compose lui-même sa navigation et
          son pied de page. Il n'avait donc ni repère `main` ni lien d'évitement — la page
          la plus visitée du site était la seule sans structure de repères. */}
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-brand-dark focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        Aller au contenu principal
      </a>
      <Navbar />
      <DefiBandeau />

      <main id="contenu">

      {/* ═══════════ HERO (image plein cadre + dynamisme, style palmarès) ═══════════ */}
      {/* Hauteur : EXACTEMENT l'écran visible sous la barre de navigation (64 px).
          L'ancienne version (88vh + 112 px de marge haute) débordait sur téléphone :
          il fallait faire défiler pour atteindre les boutons et les chiffres. Sur
          petit écran, titre, chapeau, boutons et cartes sont resserrés pour tenir
          dans le premier écran, centrés. */}
      <section className="relative isolate flex min-h-[calc(100svh_-_4rem)] flex-col overflow-hidden">
        {/* Image plein cadre + Ken Burns */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/hero-1600.webp" width={1600} height={1067} alt="Départ d'une course de chevaux aux portes numérotées"
          srcSet="/img/hero-640.webp 640w, /img/hero-1024.webp 1024w, /img/hero-1600.webp 1600w"
          sizes="100vw"
          fetchPriority="high" decoding="async"
          className="absolute inset-0 h-full w-full object-cover object-[68%_center] ken-burns" />
        {/* Dégradés sombres (lisibilité texte blanc) + halo or pour la profondeur */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/60 to-black/40" />
        <div className="absolute inset-0 bg-gradient-to-r from-black/55 via-transparent to-transparent" />
        <div className="tr-glow pointer-events-none absolute left-1/2 top-1/3 h-[420px] w-[420px] -translate-x-1/2 rounded-full bg-amber-500/15 blur-[90px]" aria-hidden="true" />

        <div className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 py-5 text-center sm:px-6 sm:py-16 lg:px-8">
          <p className="flex items-center justify-center gap-3 text-[10px] font-semibold uppercase tracking-[0.24em] text-amber-300 sm:text-[11px]">
            <span className="h-px w-6 bg-amber-400/70 sm:w-7" aria-hidden="true" />
            Pronostics hippiques IA
            <span className="h-px w-6 bg-amber-400/70 sm:w-7" aria-hidden="true" />
          </p>
          {/* Le titre de la page ne nommait pas ce qui analyse les courses, alors que
              c'est tout le sujet du site et que le champ lexical revient trente-cinq fois
              plus bas. « par l'IA » n'est pas un ajout décoratif : un modèle statistique
              réentraîné chaque nuit calcule bien la probabilité de chaque partant. */}
          <h1 className="mt-3 font-display text-[1.9rem] font-extrabold leading-[1.08] tracking-tight text-white [text-shadow:0_2px_24px_rgba(0,0,0,0.55)] sm:mt-6 sm:text-[4.25rem] sm:leading-[1.02]">
            Chaque course du PMU,{" "}
            <span className="text-gradient-animated">analysée par l&apos;IA avant le départ.</span>
          </h1>

          <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-white/85 sm:mt-6 sm:text-lg">
            80 critères par cheval, une probabilité par partant, et un{" "}
            <span className="font-semibold text-white">plan de mise</span> calculé sur votre budget.
            <span className="hidden sm:inline"> Nos pronostics sont notés à l&apos;arrivée, aux rapports PMU officiels —</span>{" "}
            <span className="font-semibold text-white"><span className="sm:hidden">Palmarès</span><span className="hidden sm:inline">tout le palmarès est</span> public</span>.
          </p>

          <div className="mx-auto mt-5 grid w-full max-w-md grid-cols-2 gap-2 sm:mt-8 sm:flex sm:max-w-none sm:justify-center sm:gap-3">
            <Button size="xl" asChild
              className="press btn-shimmer h-auto min-h-12 whitespace-normal rounded-xl bg-brand-gold px-2 py-2 text-center text-sm font-bold leading-tight text-brand-dark shadow-lg shadow-amber-500/30 hover:bg-brand-gold-deep sm:h-14 sm:px-10 sm:text-base">
              <Link href="/tarifs#passes">Débloquer dès 5&nbsp;€ <ArrowRight className="ml-1 hidden h-5 w-5 sm:inline" /></Link>
            </Button>
            <Button variant="outline" size="xl" asChild
              className="press h-auto min-h-12 whitespace-normal rounded-xl border-white/25 bg-white/10 px-2 py-2 text-center text-sm leading-tight text-white backdrop-blur-sm hover:bg-white/20 hover:text-white sm:h-14 sm:px-10 sm:text-base">
              <Link href="/programme"><span className="sm:hidden">Courses du jour</span><span className="hidden sm:inline">Voir les courses du jour</span></Link>
            </Button>
          </div>
          <p className="mt-3 text-[11px] text-white/60 sm:mt-5">Pass Jour 5&nbsp;€ sans abonnement<span className="hidden sm:inline"> · compte gratuit : 1 classement par jour</span></p>

          {/* Stats clés — cartes verre + count-up (live, mêmes chiffres que le palmarès) */}
          <HeroStats
            fallback={{
              accuracy_top3: tr?.accuracy_top3 ?? null,
              favori_place_rate: tr?.favori_place_rate ?? null,
              courses_analysees: tr?.nb_courses ?? null,
            }}
          />
        </div>

        <a
          href="#fonctionnement"
          className="relative mx-auto mb-5 hidden flex-col items-center gap-1 text-[11px] font-medium uppercase tracking-[0.2em] text-white/60 transition-colors hover:text-amber-300 md:flex"
        >
          Découvrir
          <ChevronDown className="h-5 w-5 animate-bounce" aria-hidden="true" />
        </a>
      </section>

      <LiveTicker initial={palmares} />

      {/* ═══════════ COMMENT ÇA MARCHE ═══════════ */}
      <section id="fonctionnement" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <p className="mb-4 text-sm text-stone-500">Comment ça marche</p>
              <h2 className="font-display text-[1.65rem] leading-tight sm:text-4xl font-medium tracking-tight text-stone-900">
                Le travail est déjà fait quand vous arrivez
              </h2>
              <p className="text-stone-500 text-base mt-4 max-w-2xl mx-auto">
                Vous n&apos;avez ni base de données à monter, ni modèle à entraîner : trois gestes suffisent.
              </p>
            </div>
          </ScrollReveal>
          <EtapesFonctionnement />
        </div>
      </section>

      <div className="section-divider" />

      {/* ═══════════ PERFORMANCES (chiffres clés, grille bento sombre) ═══════════ */}
      <section id="preuves" className="relative scroll-mt-20 overflow-hidden bg-[#0B0A08] py-20 sm:py-28">
        <span aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-amber-500/[0.08] blur-3xl" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="mb-12 max-w-2xl">
            <p className="text-sm font-medium text-amber-300/90">Performances vérifiables</p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-white sm:text-5xl">
              Des résultats mesurés.<br className="hidden sm:block" /> Pas des promesses.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-white/55">
              Chaque pronostic est figé avant le départ, puis comparé à l&apos;arrivée officielle PMU et à ce que
              ferait un tirage au sort sur la même course. Rien n&apos;est réécrit après coup.
            </p>
          </div>

          {tr && <PerformancesBento m={tr} />}

          <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <Link href="/track-record" className="press inline-flex min-h-12 items-center gap-1.5 rounded-full bg-white px-6 text-sm font-semibold text-stone-950 transition-transform hover:-translate-y-0.5">
              Voir toutes nos performances <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            <p className="max-w-md text-[11px] leading-relaxed text-white/35">
              La précision mesure la qualité du classement des chevaux : ce n&apos;est ni un taux de gain, ni une garantie de profit.
              Les performances passées ne préjugent pas des performances futures.
            </p>
          </div>
        </div>
      </section>

      {/* ═══════════ PALMARÈS EN DIRECT (paris gagnés réels) ═══════════ */}
      <LivePalmares initial={palmares} />

      {/* ═══════════ OUTSIDERS DU JOUR (cerveau des outsiders) ═══════════ */}
      <section id="outsiders" className="scroll-mt-20 bg-white py-16 sm:py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <OutsidersDuJour />
        </div>
      </section>


      {/* ═══════════ DÉFI DU MOIS — le concept et le classement en direct ═══════════ */}
      <section id="defi" className="scroll-mt-20 bg-[#FBF8F1] py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
                <Trophy className="h-3.5 w-3.5" aria-hidden="true" /> Nouveau · gratuit
              </span>
              <h2 className="mt-4 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                Le Défi du mois : vos pronostics contre ceux des autres
              </h2>
              <p className="mt-3 max-w-xl text-base leading-relaxed text-slate-600">
                Chaque mois, 1 000 points pour parier sur les courses, avec vos propres chevaux ou ceux de nos plans de mise.
                Les gains se calculent au rapport PMU officiel, et le meilleur solde remporte 30 jours Expert.
                Aucun argent réel n&apos;est en jeu.
              </p>
              <DefiConcept className="mt-6 lg:grid-cols-2" />
              <Link href="/defi" className="press mt-6 inline-flex min-h-12 items-center gap-1.5 rounded-full bg-amber-800 px-6 text-sm font-semibold text-white shadow-lg shadow-amber-900/20">
                Découvrir le défi <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
            <DefiClassementLive top={5} className="lg:sticky lg:top-24" />
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ═══════════ OUTILS EN VRAIS ÉCRANS (repris de /decouvrir) ═══════════ */}
      <OutilsEnEcrans id="produit" />

      {/* ═══════════ FORMULES ═══════════ */}
      <FormulesSimples id="tarifs" inscription="/inscription?suite=%2Fprogramme" />

      {/* ═══════════ FAQ (+ données structurées FAQPage) ═══════════
          Les questions posées ici sont celles qui bloquent réellement une
          inscription — y compris « est-ce que je vais gagner ? », à laquelle on
          répond non. Le JSON-LD reprend EXACTEMENT le texte visible : Google
          déclasse les FAQ dont le balisage ne correspond pas au contenu affiché. */}
      <section id="faq" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-10">
              <span className="mb-3 inline-flex items-center gap-2 rounded-full bg-amber-100/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-amber-900 ring-1 ring-amber-200">
                <Shield className="h-3.5 w-3.5" /> Questions fréquentes
              </span>
              <h2 className="font-display text-[1.65rem] leading-tight sm:text-4xl font-extrabold tracking-tight text-gray-900">
                Les réponses{" "}
                <span className="text-gradient">sans détour</span>
              </h2>
            </div>
          </ScrollReveal>

          <div className="space-y-3">
            {FAQ.map((f, i) => (
              <ScrollReveal key={f.q} delay={i * 60}>
                <details className="group rounded-2xl bg-white px-5 py-4 ring-1 ring-gray-200 transition-shadow hover:shadow-[0_16px_36px_-28px_rgba(17,24,39,.5)] open:bg-amber-50/40 open:ring-amber-300">
                  <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-[15px] font-semibold text-gray-900 marker:content-none">
                    {f.q}
                    <ChevronRight className="h-4 w-4 shrink-0 text-brand-gold-dark transition-transform group-open:rotate-90" />
                  </summary>
                  <p className="mt-3 text-sm leading-6 text-gray-600">{f.r}</p>
                </details>
              </ScrollReveal>
            ))}
          </div>

          <p className="mt-8 text-center text-sm text-gray-600">
            Une autre question ?{" "}
            <Link href="/tarifs" className="font-semibold text-brand-gold-dark underline-offset-4 hover:underline">
              Voir le détail des formules
            </Link>
          </p>
        </div>
      </section>

      {/* ═══════════ LETTRE HEBDOMADAIRE ═══════════ */}
      {/* Placée AVANT la CTA d'abonnement : un visiteur qui n'est pas prêt à payer
          repartait jusqu'ici sans laisser de trace. C'est la fuite la plus coûteuse
          du tunnel sur un produit qu'on n'achète pas au premier contact. */}
      <section className="bg-brand-warm py-16 border-t border-gray-200">
        <div className="mx-auto max-w-2xl px-5 sm:px-6">
          <NewsletterForm source="accueil" />
        </div>
      </section>

      {/* ═══════════ CTA FINALE — photo ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/cta.webp" width={1600} height={1064} alt="Arrivée d'une course devant le public" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover ken-burns" />
        <div className="absolute inset-0 bg-gray-950/75" />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950 via-gray-950/40 to-gray-950/70" />
        <div className="relative mx-auto max-w-3xl px-4 sm:px-6 text-center py-24 sm:py-32">
          <ScrollReveal>
            <span className="badge-pulse eyebrow px-4 py-1.5 rounded-full bg-white/10 text-amber-200 border border-white/20 text-[11px] font-semibold mb-6">
              Commencez aujourd&apos;hui
            </span>
            <h2 className="font-display text-3xl sm:text-5xl font-extrabold text-white mb-5 leading-tight">
              Pariez avec{" "}
              <span className="text-gradient-animated">une méthode</span>
              {" "}— pas avec votre instinct.
            </h2>
            <p className="text-gray-200 text-lg mb-10 max-w-xl mx-auto">
              Des analyses chiffrées et vérifiées sur les vrais résultats du PMU. Tout BlackTurf dès
              5&nbsp;€ avec le Pass Jour, sans abonnement : l&apos;accès se coupe seul au bout de 24&nbsp;h.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button size="xl" asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-brand-dark font-bold text-base shadow-xl shadow-amber-900/40">
                <Link href="/tarifs#passes">Débloquer dès 5 € <ArrowRight className="h-5 w-5 ml-1" /></Link>
              </Button>
              <Button variant="outline" size="xl" asChild
                className="press border-white/30 bg-white/5 text-white hover:bg-white/15 hover:border-white/50">
                <Link href="/inscription">Créer un compte gratuit</Link>
              </Button>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ═══════════ JEU RESPONSABLE ═══════════ */}
      <section className="py-8 border-t border-gray-100 bg-brand-warm">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <p className="text-xs text-gray-600 leading-relaxed inline-flex flex-wrap items-center justify-center gap-x-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-gray-600 inline" />
            <span><strong className="text-gray-600">Jeu responsable.</strong> BlackTurf est un outil d&apos;aide à la décision,
            pas une garantie de gain. Les performances passées ne préjugent pas des performances futures.
            Interdit aux mineurs. En cas de difficulté :{" "}
            <a href="https://www.joueurs-info-service.fr" target="_blank" rel="noopener noreferrer" className="underline hover:text-gray-600 transition-colors">joueurs-info-service.fr</a>
            {" "}— <strong className="text-gray-600">09 74 75 13 13</strong> (gratuit, 7j/7, 8h-2h).</span>
          </p>
        </div>
      </section>

      </main>

      <Footer />
      <BottomNav />
    </div>
  );
}
