import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight, TrendingUp, Zap, Shield, Trophy,
  Bell, Calculator, ChevronRight, Check, Target,
  Sparkles, Database, AlertTriangle, BarChart3, Wallet, Search, Star, Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { ScrollReveal } from "@/components/ui/ScrollReveal";
import { LiveTicker } from "@/components/ui/LiveTicker";
import { CalculatorDemo } from "@/components/home/CalculatorDemo";
import { LivePalmares } from "@/components/home/LivePalmares";
import { HeroStats } from "@/components/home/HeroStats";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";

// Le canonical n'est plus hérité de la racine (il y désignait "/" pour TOUTES les pages) :
// l'accueil déclare donc le sien explicitement.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

// ─── Exemple de course (illustratif, tagué « Exemple » partout) ──────────────
const EXAMPLE = { hippo: "Deauville", code: "R4 · C5", disc: "Plat · 1600m" };
const EXAMPLE_PICKS = [
  { rank: 1, num: 2, nom: "Paladin Noir", cote: "3,4", p: 42 },
  { rank: 2, num: 4, nom: "Royal Flush", cote: "5,1", p: 28 },
  { rank: 3, num: 7, nom: "Vent d'Est", cote: "8,5", p: 19 },
];

// Plans de mise PAR PROFIL — reflet du vrai outil (Prudent / Modéré / Risqué).
// Gains = potentiels SI le pari passe, à titre d'illustration.
const PROFILS = [
  {
    key: "prudent", emoji: "🛡️", name: "Prudent", tagline: "Des gains réguliers, le risque minimal",
    dot: "#059669",
    bets: [
      { type: "Placé", chevaux: "N°2", mise: "3€", gain: "≈ 6€" },
      { type: "Couplé Placé", chevaux: "2 · 4", mise: "2€", gain: "≈ 14€" },
    ],
  },
  {
    key: "modere", emoji: "⚖️", name: "Modéré", tagline: "L'équilibre rendement / sécurité", popular: true,
    dot: "#B45309",
    bets: [
      { type: "Couplé Placé", chevaux: "2 · 4 · 5", mise: "3€", gain: "≈ 32€" },
      { type: "2 sur 4", chevaux: "2 · 4 · 5 · 7", mise: "2€", gain: "≈ 48€" },
    ],
  },
  {
    key: "risque", emoji: "🔥", name: "Risqué", tagline: "On vise les gros gains",
    dot: "#D97706",
    bets: [
      { type: "Couplé Gagnant", chevaux: "2 · 4", mise: "2€", gain: "≈ 259€" },
      { type: "Tiercé", chevaux: "2 · 4 · 5", mise: "2€", gain: "≈ 430€" },
    ],
  },
];

// Suivi de capital — exemple de paris RÉGLÉS (mix gagné/perdu : transparence, pas de promesse).
const CAPITAL_DEPART = 100;
const CAPITAL_DEMO = [
  { type: "Couplé Placé", chevaux: "2 · 4", mise: 6, won: true, net: 12 },
  { type: "Simple Placé", chevaux: "N°6", mise: 4, won: false, net: -4 },
  { type: "2 sur 4", chevaux: "1 · 3 · 5 · 8", mise: 4, won: true, net: 24 },
  { type: "Couplé Gagnant", chevaux: "4 · 7", mise: 4, won: false, net: -4 },
  { type: "Simple Placé", chevaux: "N°3", mise: 4, won: true, net: 6 },
];
const CAPITAL_NET = CAPITAL_DEMO.reduce((s, b) => s + b.net, 0);
const CAPITAL_WINS = CAPITAL_DEMO.filter((b) => b.won).length;

const ICON_GOLD = { color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.16)" };
const FEATURE_MAIN = {
  icon: Target,
  title: "80+ critères analysés pour chaque cheval",
  desc: "Là où l'œil humain en retient une poignée, BlackTurf croise tout ce que le marché regarde — et ce qu'il oublie — puis se recale sur l'arrivée réelle après chaque réunion.",
  categories: [
    { label: "Forme & niveau", items: ["Forme sur 5 courses", "Régularité au podium", "ELO global + par discipline", "Progression & momentum"] },
    { label: "Conditions de course", items: ["Affinité terrain & pénétromètre", "Distance de prédilection", "Corde / numéro de départ", "Poids porté & allègement"] },
    { label: "Hommes & historique", items: ["Forme jockey & écurie", "Association jockey × entraîneur", "Confrontations directes", "Pedigree du père"] },
    { label: "Marché & signaux", items: ["Mouvements de cote", "SPI — argent professionnel", "Écart PMU / Betfair", "Vitesse (réduction km) & fraîcheur"] },
  ],
};
const FEATURES = [
  { icon: Zap, title: "Seulement la vraie valeur", desc: "Un pari n'est signalé que si la probabilité réelle dépasse ce que paie la cote. Des chiffres, pas un coup de cœur.", ...ICON_GOLD },
  { icon: Calculator, title: "Plan de mise sur mesure", desc: "Vous donnez votre budget, vous recevez une répartition sécurité / rendement / coup selon votre profil.", ...ICON_GOLD },
  { icon: Wallet, title: "Votre capital, sans enjolivure", desc: "Chaque pari réglé aux vrais rapports PMU. Votre rendement réel, suivi au centime.", ...ICON_GOLD },
  { icon: Bell, title: "Alertes & assistant", desc: "Push, e-mail, digest matinal. Et vos questions sur une course, en langage naturel.", ...ICON_GOLD },
  { icon: Database, title: "100 % données réelles", desc: "Programme et résultats PMU officiels. Aucun chiffre inventé : une donnée inconnue reste « — ».", ...ICON_GOLD },
];

const PLANS = [
  { name: "Découverte", price: "0€", period: "/mois", desc: "Découvrez la plateforme",
    features: ["Programme du jour", "Cotes publiques", "1 pronostic/jour", "Statistiques publiques vérifiées"],
    cta: "Commencer gratuitement", href: "/inscription", popular: false },
  { name: "Standard", price: "12€", period: "/mois", desc: "L'essentiel pour parier mieux",
    features: ["5 pronostics/jour", "Top 3 paris de valeur (délai 15 min)", "Calculateur de mise", "Suivi du capital + statistiques", "Alertes push & e-mail", "Historique des résultats"],
    cta: "Essayer 7 jours gratuit", href: "/inscription?plan=standard", popular: false },
  // Expert = plan mis en avant (aligné sur /tarifs, qui le marque « Recommandé »).
  // CTA « Essayer 7 jours gratuit » comme Standard : depuis le 2026-08-17 l'essai de
  // 7 jours s'applique AUSSI à Expert (cf. subscription_data dans stripe_routes.py).
  { name: "Expert", price: "19€", period: "/mois", desc: "Pour les parieurs sérieux", badge: "Populaire",
    features: ["Pronostics illimités", "Paris de valeur en temps réel ★★★★", "Calculateur de mise avancé", "Assistant illimité", "Performances détaillées par discipline", "Créateur de stratégies 30+ filtres", "Export des données"],
    cta: "Essayer 7 jours gratuit", href: "/inscription?plan=expert", popular: true },
];

const DISC_LABEL: Record<string, string> = {
  plat: "Plat", "attelé": "Trot attelé", attele: "Trot attelé",
  "monté": "Trot monté", monte: "Trot monté", obstacle: "Obstacle", autre: "Autre",
};

const numOf = (x: unknown): number | null =>
  typeof x === "number" && !Number.isNaN(x) ? x : null;

interface TrackRecord {
  accuracy_top1: number | null;
  accuracy_top3: number | null;
  favori_place_rate: number | null;
  favori_win_rate: number | null;
  nb_courses: number | null;
  mesure_depuis: string | null;
  hasard_top3: number | null;
  hasard_top1: number | null;
  by_discipline: Array<{ discipline: string; nb_courses: number; accuracy_top3: number }>;
  by_day: Array<{ jour: string; accuracy_top3: number; nb_predictions: number }>;
}

// Questions qui bloquent réellement une inscription — la deuxième répond « non »
// à « est-ce que je vais gagner ». Une FAQ qui ne dit que du bien ne rassure
// personne, et le balisage FAQPage exige de toute façon le texte affiché.
function buildFaq(tr: TrackRecord | null): Array<{ q: string; r: string }> {
  const pc = (x: number | null, d = 1) => (x == null ? null : `${x.toFixed(d).replace(".", ",")} %`);
  const top3 = pc(tr?.accuracy_top3 ?? null);
  const hasard = pc(tr?.hasard_top3 ?? null, 0);
  const nb = tr?.nb_courses ? tr.nb_courses.toLocaleString("fr-FR") : null;
  return [
    {
      q: "Concrètement, que fait BlackTurf ?",
      r: "Nous analysons chaque course du programme PMU avant le départ : plus de 80 critères par cheval (forme, terrain, distance, jockey, mouvements de cote…), une probabilité pour chaque partant, puis un plan de mise calculé selon votre budget et votre tolérance au risque. Vous gardez la main : vous pariez où vous voulez, et nous ne prenons aucune commission sur vos gains.",
    },
    {
      q: "Est-ce que je vais gagner de l'argent ?",
      r: `Personne ne peut vous le garantir, et nous ne le ferons pas : le pari hippique reste soumis au prélèvement de l'opérateur et au hasard. Ce que nous publions, c'est la qualité de l'analyse${top3 && hasard ? ` — le gagnant figure dans notre Top-3 sur ${top3} des courses, contre ${hasard} pour un tirage au sort` : ""}, et le détail de chaque pari réglé, gagnant comme perdant.`,
    },
    {
      q: "Combien de temps ça me prend ?",
      r: "Le temps de lire une fiche. Quand vous arrivez, la course est déjà analysée : vous choisissez la course, vous entrez votre mise, le plan s'affiche. Les alertes préviennent quand un pari de valeur apparaît — pas besoin de surveiller le programme toute la journée.",
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
      r: "À tout moment depuis votre compte, en deux clics. L'essai de 7 jours demande une carte, mais rien n'est prélevé avant son terme : annulez avant la fin et vous ne payez rien.",
    },
  ];
}

async function fetchTrackRecord(): Promise<TrackRecord | null> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/track-record`, { next: { revalidate: 3600 } });
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
  } catch { return null; }
}

export default async function HomePage() {
  const tr = await fetchTrackRecord();
  const fmtPct = (x: number | null, dec = 1) => (x == null ? "—" : `${x.toFixed(dec).replace(".", ",")}%`);
  const fmtInt = (x: number | null) => (x == null ? "—" : x.toLocaleString("fr-FR"));
  const FAQ = buildFaq(tr);
  // FAQPage : le balisage reprend mot pour mot les questions/réponses affichées.
  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.r },
    })),
  };

  return (
    <div className="flex flex-col min-h-screen bg-brand-warm">
      <Navbar />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }} />

      {/* ═══════════ HERO (image plein cadre + dynamisme, style palmarès) ═══════════ */}
      <section className="relative overflow-hidden border-b border-border/40 min-h-[88vh] flex items-center">
        {/* Image plein cadre + Ken Burns */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/hero-1600.webp" width={1600} height={1067} alt="Départ d'une course de chevaux aux portes numérotées"
          srcSet="/img/hero-640.webp 640w, /img/hero-1024.webp 1024w, /img/hero-1600.webp 1600w"
          sizes="100vw"
          fetchPriority="high" decoding="async"
          className="absolute inset-0 h-full w-full object-cover object-[68%_center] ken-burns" />
        {/* Dégradés sombres (lisibilité texte blanc) */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/55 to-black/35" />
        <div className="absolute inset-0 bg-gradient-to-r from-black/55 via-transparent to-transparent" />

        <div className="relative mx-auto max-w-5xl w-full px-5 sm:px-6 lg:px-8 pt-28 pb-16 text-center">
          <h1 className="font-display text-[2.4rem] leading-[1.04] sm:text-[4.25rem] sm:leading-[1.02] font-extrabold tracking-tight text-white [text-shadow:0_2px_24px_rgba(0,0,0,0.55)]">
            Chaque course du PMU,{" "}
            <span className="text-gradient-animated">analysée avant le départ.</span>
          </h1>

          <p className="mt-6 text-base sm:text-lg text-white/85 leading-relaxed max-w-2xl mx-auto">
            80 critères par cheval, une probabilité par partant, et un{" "}
            <span className="font-semibold text-white">plan de mise</span> calculé sur votre budget.
            Nos pronostics sont notés à l&apos;arrivée, aux rapports PMU officiels —{" "}
            <span className="font-semibold text-white">tout le palmarès est public</span>.
          </p>

          <div className="mt-8 flex flex-col sm:flex-row justify-center gap-3">
            <Button size="xl" asChild
              className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-lg shadow-amber-500/30">
              <Link href="/inscription">Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" /></Link>
            </Button>
            <Button variant="outline" size="xl" asChild
              className="press bg-white/10 backdrop-blur-sm border-white/25 text-white hover:bg-white/20 hover:text-white">
              <Link href="/programme">Voir le programme du jour</Link>
            </Button>
          </div>
          <p className="mt-5 text-[11px] text-white/55">7 jours gratuits · aucun prélèvement avant la fin de l&apos;essai · annulation à tout moment</p>

          {/* Stats clés — cartes verre + count-up (live, mêmes chiffres que le palmarès) */}
          <HeroStats
            fallback={{
              accuracy_top3: tr?.accuracy_top3 ?? null,
              favori_place_rate: tr?.favori_place_rate ?? null,
              courses_analysees: tr?.nb_courses ?? null,
            }}
          />
        </div>
      </section>

      <LiveTicker />

      {/* ═══════════ COMMENT ÇA MARCHE ═══════════ */}
      <section id="fonctionnement" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-2">
                <Zap className="h-3.5 w-3.5" /> Comment ça marche
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Le travail est déjà fait{" "}
                <span className="text-gradient">quand vous arrivez</span>
              </h2>
              <p className="text-gray-500 text-sm mt-3 max-w-2xl mx-auto">
                Vous n&apos;avez ni base de données à monter, ni modèle à entraîner : trois gestes suffisent.
              </p>
            </div>
          </ScrollReveal>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { step: "01", title: "Ouvrez la course", desc: "Tout le programme PMU du jour est déjà analysé : classement des partants, probabilité de chacun, score de confiance de la course." },
              { step: "02", title: "Donnez votre budget", desc: "Vous entrez un montant, nous répartissons : une ligne sécurité, une ligne rendement, une ligne coup — selon votre profil de risque." },
              { step: "03", title: "Pariez où vous voulez", desc: "Vous jouez chez votre opérateur. À l'arrivée, chaque pari est réglé au rapport officiel et votre capital est mis à jour." },
            ].map((s, i) => (
              <ScrollReveal key={s.step} delay={i * 100}>
                <div className={`relative h-full ${i < 2 ? "step-connector" : ""}`}>
                  <div className="glass-card tilt-card rounded-2xl p-7 h-full">
                    <div className="icon-box h-14 w-14 rounded-2xl flex items-center justify-center font-mono font-black text-lg mb-5"
                      style={{ background: "#FFFBEB", border: "1px solid rgba(180,83,9,0.18)", color: "#B45309" }}>{s.step}</div>
                    <h3 className="font-semibold text-gray-900 text-base mb-2">{s.title}</h3>
                    <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                  </div>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ═══════════ PREUVES RÉELLES (track-record) ═══════════ */}
      <section id="preuves" className="py-24 bg-brand-warm scroll-mt-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="mb-12 text-center">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Shield className="h-3.5 w-3.5" /> Performances vérifiables
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Des résultats vérifiables.<br className="hidden sm:block" /> Pas des promesses.
              </h2>
              <p className="text-gray-500 text-sm mt-3 max-w-2xl mx-auto">
                Aucun pronostic n'est réécrit après la course. Voici la précision réelle de BlackTurf sur les
                courses déjà réglées, et ce que ferait un tirage au sort sur les mêmes courses.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {[
              { value: fmtPct(tr?.accuracy_top3 ?? null), label: "Précision Top-3", sub: "un de nos 3 favoris finit dans les 3", accent: true, icon: Target },
              { value: fmtPct(tr?.favori_place_rate ?? null), label: "Notre favori placé", sub: "notre n°1 dans les 3 premiers", icon: Shield },
              { value: fmtPct(tr?.favori_win_rate ?? null), label: "Notre favori gagnant", sub: "notre n°1 remporte la course", icon: Trophy },
              { value: fmtInt(tr?.nb_courses ?? null), label: "Courses vérifiées", sub: "réglées aux résultats PMU officiels", icon: Database },
            ].map((m, i) => (
              <ScrollReveal key={m.label} delay={i * 70}>
                <div className="tilt-card relative overflow-hidden rounded-2xl border border-gray-200 bg-white px-5 py-5 shadow-sm h-full">
                  <m.icon className="absolute right-3 top-3 h-5 w-5 text-amber-300/60" />
                  <div className="num-display text-3xl sm:text-[2.1rem] font-extrabold" style={{ color: m.accent ? "#B45309" : "#111827" }}>{m.value}</div>
                  <p className="text-sm font-semibold text-gray-900 mt-1">{m.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{m.sub}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>

          {/* Les taux ci-dessus ne portent que sur la cohorte rejouable (snapshots
              pre-course). Tant qu'elle est petite, on le dit plutot que de laisser
              lire un pourcentage comme un acquis. */}
          <EchantillonNotice nbCourses={tr?.nb_courses} mesureDepuis={tr?.mesure_depuis} />

          <div className="grid lg:grid-cols-2 gap-4">
            {tr && tr.by_discipline.length > 0 && (
              <ScrollReveal>
                <div className="glass-card rounded-2xl p-6 h-full">
                  <div className="flex items-center gap-2 mb-5">
                    <BarChart3 className="h-4 w-4 text-brand-gold-deep" />
                    <h3 className="font-semibold text-gray-900 text-sm">Précision Top-3 par discipline</h3>
                  </div>
                  <div className="space-y-4">
                    {tr.by_discipline.map((d) => (
                      <div key={d.discipline}>
                        <div className="flex items-center justify-between text-xs mb-1.5">
                          <span className="font-semibold text-gray-700">{DISC_LABEL[d.discipline] ?? d.discipline}</span>
                          <span className="num-display font-bold text-gray-900">{d.accuracy_top3.toFixed(1).replace(".", ",")}%
                            <span className="text-gray-500 font-normal ml-1.5">· {d.nb_courses} courses</span>
                          </span>
                        </div>
                        <div className="relative h-3 rounded-full bg-gray-100 overflow-hidden">
                          <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(d.accuracy_top3, 100)}%`, background: "linear-gradient(90deg,#D97706,#F59E0B)" }} />
                          {/* repère 33% (hasard) */}
                          {tr.hasard_top3 != null && (
                            <div className="absolute top-0 bottom-0 w-px bg-gray-500/40" style={{ left: `${Math.min(tr.hasard_top3, 100)}%` }} />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-5 flex items-center gap-1.5 text-[11px] text-gray-500">
                    <span className="inline-block w-px h-3 bg-gray-400/60" />
                    {tr.hasard_top3 != null
                      ? `Repère « hasard » à ${tr.hasard_top3.toFixed(0)} % — l'espérance d'un tirage au sort sur ces mêmes courses. Au-delà, l'analyse fait mieux.`
                      : "Au-delà du repère du hasard, l'analyse fait mieux."}
                  </div>
                </div>
              </ScrollReveal>
            )}

            {tr && tr.by_day.length > 0 && (() => {
              const avg = tr.by_day.reduce((s, d) => s + d.accuracy_top3, 0) / tr.by_day.length;
              return (
              <ScrollReveal delay={80}>
                <div className="glass-card rounded-2xl p-6 h-full flex flex-col">
                  <div className="flex items-center justify-between mb-5">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-emerald-600" />
                      <h3 className="font-semibold text-gray-900 text-sm">Précision Top-3 · 7 derniers jours</h3>
                    </div>
                    <span className="text-[11px] text-gray-500">moy. <span className="num-display font-bold text-gray-700">{avg.toFixed(0)}%</span></span>
                  </div>

                  {/* Aire de chart à hauteur FIXE → barres % fiables */}
                  <div className="relative h-44">
                    {/* lignes repères */}
                    {[25, 50, 75].map((g) => (
                      <div key={g} className="absolute left-0 right-0 border-t border-dashed border-gray-100" style={{ bottom: `${g}%` }} />
                    ))}
                    {/* ligne moyenne */}
                    <div className="absolute left-0 right-0 border-t border-dashed border-emerald-300" style={{ bottom: `${Math.min(avg, 100)}%` }}>
                      <span className="absolute right-0 -top-3.5 text-[9px] font-semibold text-emerald-500 bg-white px-1">moyenne</span>
                    </div>
                    <div className="absolute inset-0 flex items-end justify-between gap-2.5">
                      {tr.by_day.map((d) => (
                        <div key={d.jour} className="group relative flex h-full flex-1 flex-col items-center justify-end">
                          <span className="num-display text-[10px] font-bold text-gray-700 mb-1">{Math.round(d.accuracy_top3)}%</span>
                          <div className="w-full max-w-[40px] rounded-t-lg bg-gradient-to-t from-amber-300 to-amber-500 shadow-sm transition-all duration-300 group-hover:from-amber-400 group-hover:to-amber-600"
                            style={{ height: `${Math.max(4, Math.min(d.accuracy_top3, 100))}%` }}
                            title={`${d.jour} · ${d.accuracy_top3.toFixed(1)}% · ${d.nb_predictions} pronostics`} />
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="mt-2 flex justify-between gap-2.5">
                    {tr.by_day.map((d) => (
                      <span key={d.jour} className="flex-1 text-center text-[9px] text-gray-500">{d.jour}</span>
                    ))}
                  </div>
                  <p className="mt-4 text-[11px] text-gray-500">Jour par jour, sur les pronostics réglés aux arrivées PMU officielles.</p>
                </div>
              </ScrollReveal>
              );
            })()}
          </div>

          <p className="mt-6 text-center text-[11px] text-gray-500 max-w-2xl mx-auto leading-relaxed">
            La précision d'analyse mesure la qualité du classement des chevaux. Ce n'est ni un taux de
            gain, ni une garantie de profit. Les performances passées ne préjugent pas des performances futures.
          </p>
        </div>
      </section>

      {/* ═══════════ PALMARÈS EN DIRECT (paris gagnés réels) ═══════════ */}
      <LivePalmares />

      <div className="section-divider" />

      {/* ═══════════ PRONOSTICS PAR PROFIL DE RISQUE (vrai outil) ═══════════ */}
      <section id="produit" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Target className="h-3.5 w-3.5" /> Le cœur de BlackTurf
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Un plan de mise{" "}
                <span className="text-gradient">selon votre profil</span>
              </h2>
              <p className="text-gray-500 text-sm mt-3 max-w-2xl mx-auto">
                Même course, trois façons de jouer. Vous choisissez votre profil et votre budget —
                BlackTurf construit les paris adaptés et calcule le gain potentiel de chacun.
              </p>
            </div>
          </ScrollReveal>

          {/* Course exemple + portrait */}
          <div className="grid lg:grid-cols-3 gap-5 mb-6">
            <ScrollReveal className="lg:col-span-1">
              <div className="glass-card rounded-2xl p-5 h-full">
                <div className="flex items-center justify-between">
                  <span className="eyebrow text-amber-700 text-[10px] font-bold">
                    <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" /> Pronostic BlackTurf
                  </span>
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-wider text-white bg-brand-gold-deep rounded px-1.5 py-0.5">{EXAMPLE.hippo}</span>
                  <span className="text-xs text-gray-500 font-mono">{EXAMPLE.code} · {EXAMPLE.disc}</span>
                </div>
                <div className="mt-3 space-y-1.5">
                  {EXAMPLE_PICKS.map((h) => (
                    <div key={h.rank} className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${h.rank === 1 ? "bg-amber-50 ring-1 ring-amber-200" : "bg-gray-50"}`}>
                      <span className={`num-display text-xs font-black w-7 ${h.rank === 1 ? "text-brand-gold-deep" : "text-gray-500"}`}>N°{h.num}</span>
                      <span className="text-sm font-medium text-gray-900 flex-1 truncate">{h.nom}</span>
                      <span className="num-display text-xs font-bold text-gray-700 w-9 text-right">{h.p}%</span>
                      <span className="text-[11px] font-mono text-gray-500 w-8 text-right">{h.cote}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 font-semibold text-emerald-700"><Zap className="h-3 w-3" /> Valeur ★★★ détectée</span>
                  <span className="text-gray-500">EV <span className="num-display font-bold text-emerald-600">+14,2%</span></span>
                </div>
              </div>
            </ScrollReveal>

            {/* Portrait photo */}
            <ScrollReveal className="lg:col-span-2" delay={80}>
              <div className="relative rounded-2xl overflow-hidden h-full min-h-[220px]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/portrait.webp" width={1067} height={1600} alt="Cheval et jockey en tête de course" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover ken-burns" />
                <div className="absolute inset-0 bg-gradient-to-t from-gray-950/85 via-gray-950/20 to-transparent" />
                <div className="absolute bottom-0 left-0 p-6">
                  <p className="text-white font-display text-xl font-bold leading-snug max-w-xs">Les bons chevaux, au bon prix, selon votre tolérance au risque.</p>
                </div>
              </div>
            </ScrollReveal>
          </div>

          {/* 3 profils */}
          <div className="grid md:grid-cols-3 gap-5">
            {PROFILS.map((pr, i) => (
              <ScrollReveal key={pr.key} delay={i * 90}>
                <div className={`tilt-card rounded-3xl p-6 h-full bg-white ${pr.popular ? "border-2 border-amber-300 shadow-md" : "border border-gray-200 shadow-sm"}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xl">{pr.emoji}</span>
                    <h3 className="font-display text-lg font-bold text-gray-900">{pr.name}</h3>
                    {pr.popular && <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 rounded-full px-2 py-0.5">Le + choisi</span>}
                  </div>
                  <p className="text-xs text-gray-500 mb-4">{pr.tagline}</p>
                  <div className="space-y-2">
                    {pr.bets.map((b, j) => (
                      <div key={j} className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-gray-900">{b.type}</span>
                          <span className="text-[11px] font-mono text-gray-500">{b.chevaux}</span>
                        </div>
                        <div className="mt-1 flex items-center justify-between text-xs">
                          <span className="text-gray-500">Mise <span className="font-mono font-semibold text-gray-700">{b.mise}</span></span>
                          <span className="num-display font-bold text-emerald-600">{b.gain}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-[10px] text-gray-500">Gain potentiel si le pari est gagnant.</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
          <p className="mt-6 text-center text-[11px] text-gray-500 max-w-2xl mx-auto">
            Exemple illustratif sur une course type. Les paris et gains varient selon la course, votre mise et les
            rapports PMU réels. Parier comporte un risque de perte.
          </p>
        </div>
      </section>

      {/* ═══════════ CALCULATEUR ═══════════ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <ScrollReveal direction="right" className="order-2 lg:order-1">
              <div className="glass-card rounded-3xl p-2">
                <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
                  <Calculator className="h-4 w-4 text-brand-gold-deep" />
                  <span className="text-xs font-semibold text-gray-700">Calculateur de mise</span>
                  <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-gray-500 border border-gray-200 rounded-full px-2 py-0.5">Démo</span>
                </div>
                <CalculatorDemo />
              </div>
            </ScrollReveal>
            <ScrollReveal direction="left" className="order-1 lg:order-2">
              <div>
                <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                  <Calculator className="h-3.5 w-3.5" /> Essayez maintenant
                </span>
                <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
                  Votre mise, répartie au{" "}
                  <span className="text-gradient">centime près</span>
                </h2>
                <p className="text-gray-600 leading-relaxed mb-6">
                  Entrez un montant. BlackTurf construit un plan sur mesure selon votre profil de risque —
                  sécurité, rendement, coup — et calcule le gain net potentiel de chaque ligne.
                </p>
                <ul className="space-y-2.5 mb-7">
                  {["Répartition automatique par palier de risque", "Gain net potentiel calculé en direct", "Adapté à votre capital et à votre profil"].map((f) => (
                    <li key={f} className="flex items-start gap-2.5 text-sm text-gray-600">
                      <Check className="h-4 w-4 mt-0.5 flex-shrink-0 text-emerald-600" /> {f}
                    </li>
                  ))}
                </ul>
                <Link href="/programme" className="press inline-flex items-center gap-1.5 text-sm font-semibold text-brand-gold-deep hover:gap-2.5 transition-all">
                  Lancer le calculateur <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ═══════════ BANDEAU CINÉMATIQUE ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/showcase.webp" width={1600} height={1177} alt="Peloton de chevaux en pleine course" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover ken-burns" />
        <div className="absolute inset-0 bg-gradient-to-r from-gray-950 via-gray-950/85 to-gray-950/25" />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950/90 via-transparent to-gray-950/30" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-24 sm:py-32">
          <div className="max-w-xl">
            <span className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-amber-300 mb-5">
              <span className="live-dot inline-block w-2 h-2 rounded-full bg-amber-400" /> Pourquoi BlackTurf
            </span>
            <h2 className="font-display text-3xl sm:text-5xl font-extrabold text-white leading-[1.08]">
              Pendant qu'ils jouent au feeling,{" "}
              <span className="text-gradient-animated">vous jouez aux chiffres.</span>
            </h2>
            <p className="mt-5 text-base sm:text-lg text-gray-200/90 leading-relaxed max-w-lg">
              Chaque pronostic est confronté à l'arrivée réelle, puis le modèle se recale. La différence
              entre parier et parier informé se joue exactement là.
            </p>
          </div>
          {/* Inset photo */}
          <div className="hidden lg:block absolute right-8 bottom-10 w-64">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/img/duel.webp" width={1600} height={1201} alt="Duel de chevaux à l'arrivée" loading="lazy" decoding="async" className="tilt-card w-full h-40 object-cover rounded-2xl ring-1 ring-white/20 shadow-2xl" />
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-gray-300">
              <Trophy className="h-3.5 w-3.5 text-amber-300" /> Réglé aux rapports PMU officiels
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════ PARIS DE VALEUR (vrai outil) ═══════════ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <ScrollReveal direction="right">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Zap className="h-3.5 w-3.5" /> Paris de valeur
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
                Miser quand la cote{" "}
                <span className="text-gradient">se trompe</span>
              </h2>
              <p className="text-gray-600 leading-relaxed mb-6">
                Un pari « de valeur », c'est quand un cheval a plus de chances que sa cote ne le laisse croire.
                BlackTurf compare sa probabilité réelle au prix du marché et ne signale que ces écarts —
                là où, sur la durée, le jeu penche de votre côté.
              </p>
              <ul className="space-y-2.5">
                {["Probabilité du modèle vs cote du marché", "Niveaux de valeur ★ à ★★★★", "Triangulation PMU · Geny · BZH"].map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-gray-600">
                    <Check className="h-4 w-4 mt-0.5 flex-shrink-0 text-emerald-600" /> {f}
                  </li>
                ))}
              </ul>
            </ScrollReveal>

            <ScrollReveal direction="left">
              {/* Reprend la présentation RÉELLE d'une carte de /value-bets (étoiles de
                  niveau, libellé, espérance, meilleure cote + source) pour que l'aperçu
                  corresponde à ce que l'abonné voit vraiment.
                  Chiffres cohérents entre eux : cote 8,5 → proba marché 1/8,5 = 11,8 % ;
                  proba modèle 15 % → espérance = 8,5 × 0,15 − 1 = +27,5 %. */}
              <div className="glass-card rounded-3xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <span className="eyebrow text-amber-700 text-[10px] font-bold"><Zap className="h-3 w-3" /> Pari de valeur détecté</span>
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>

                <div className="rounded-2xl border border-amber-500/30 bg-amber-50/50 p-4">
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <span className="flex gap-0.5 text-amber-600" aria-label="Niveau 3 sur 4 — Fort signal">
                        {[0, 1, 2, 3].map((i) => (
                          <Star key={i} className={`h-3 w-3 ${i < 3 ? "fill-current" : "opacity-20"}`} />
                        ))}
                      </span>
                      <span className="block text-[9px] text-amber-700 mt-0.5">Fort signal</span>
                    </div>
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-500 px-1.5 py-0 text-[9px] font-medium text-amber-700">
                      <Zap className="h-2.5 w-2.5" /> Afflux marché
                    </span>
                  </div>

                  <div className="font-bold text-sm text-gray-900">Vent d&apos;Est <span className="font-mono font-normal text-gray-500">N°7</span></div>
                  <div className="text-xs text-gray-500 mt-0.5">{EXAMPLE.hippo} · {EXAMPLE.disc}</div>

                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div className="rounded-lg bg-white/70 p-2 text-center">
                      <div className="text-[10px] text-gray-500">Espérance</div>
                      <div className="num-display text-sm font-extrabold text-emerald-600">+27,5%</div>
                    </div>
                    <div className="rounded-lg bg-white/70 p-2 text-center">
                      <div className="text-[10px] font-medium text-blue-600">PMU</div>
                      <div className="num-display text-sm font-extrabold text-blue-600">8.5</div>
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                  <div className="rounded-xl bg-gray-50 p-3">
                    <div className="num-display text-lg font-extrabold text-gray-900">15%</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Proba modèle</div>
                  </div>
                  <div className="rounded-xl bg-gray-50 p-3">
                    <div className="num-display text-lg font-extrabold text-gray-500">11,8%</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">Proba marché (1/cote)</div>
                  </div>
                </div>

                <p className="mt-4 text-xs text-gray-500 leading-relaxed">
                  À 8,5, le marché lui donne ~11,8% de chances ; le modèle en voit 15%.
                  L&apos;espérance <span className="font-mono">(8,5 × 0,15) − 1 = +27,5%</span> : la cote paie plus que le risque réel.
                </p>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ═══════════ GESTION DU CAPITAL (vrai outil, image) ═══════════ */}
      <section className="relative py-24 overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/value.jpg" width={1600} height={1067} alt="Chevaux sur la piste au soleil couchant" className="absolute inset-0 h-full w-full object-cover ken-burns opacity-40" />
        <div className="absolute inset-0 bg-gradient-to-br from-gray-950 via-gray-950/80 to-gray-950/60" />
        <div className="relative mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <ScrollReveal direction="right">
              <span className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-amber-300 mb-3">
                <Wallet className="h-3.5 w-3.5" /> Gestion du capital
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-4">
                Votre bankroll,{" "}
                <span className="text-gradient-animated">suivie sans triche</span>
              </h2>
              <p className="text-gray-200/85 leading-relaxed mb-6">
                Chaque pari validé est réglé automatiquement aux vrais rapports PMU. Vous voyez votre rendement
                réel — les gains comme les pertes. Pas de chiffre maquillé : c'est ce qui vous permet de savoir
                si vous gagnez vraiment.
              </p>
              <ul className="space-y-2.5">
                {["Règlement automatique aux rapports officiels", "Rendement réel, gains ET pertes", "Critère de Kelly pour doser vos mises"].map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-gray-200/90">
                    <Check className="h-4 w-4 mt-0.5 flex-shrink-0 text-emerald-400" /> {f}
                  </li>
                ))}
              </ul>
            </ScrollReveal>

            <ScrollReveal direction="left">
              <div className="rounded-3xl bg-white/95 backdrop-blur p-5 shadow-2xl">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-gray-700">Suivi du capital</span>
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>

                {/* Capital départ → actuel (comme le vrai suivi) */}
                <div className="flex items-end justify-between rounded-xl bg-gradient-to-r from-emerald-50 to-white border border-emerald-100 px-4 py-3 mb-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-wide text-gray-500">Capital</div>
                    <div className="num-display text-lg font-extrabold text-gray-900">{CAPITAL_DEPART}€ <span className="text-gray-300 font-normal">→</span> {CAPITAL_DEPART + CAPITAL_NET}€</div>
                  </div>
                  <div className="num-display text-lg font-extrabold text-emerald-600">{CAPITAL_NET >= 0 ? "+" : ""}{CAPITAL_NET}€</div>
                </div>

                <div className="space-y-1.5">
                  {CAPITAL_DEMO.map((b, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs">
                      <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${b.won ? "bg-emerald-500" : "bg-gray-300"}`} />
                      <span className="font-semibold text-gray-800 flex-1 truncate">{b.type} <span className="font-mono font-normal text-gray-500">{b.chevaux}</span></span>
                      <span className="text-gray-500 font-mono mr-2 hidden sm:inline">{b.mise}€</span>
                      <span className={`num-display font-bold tabular-nums ${b.won ? "text-emerald-600" : "text-gray-500"}`}>{b.net >= 0 ? "+" : ""}{b.net}€</span>
                    </div>
                  ))}
                </div>

                <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between text-xs">
                  <span className="text-gray-500"><span className="font-semibold text-gray-700">{CAPITAL_WINS}/{CAPITAL_DEMO.length}</span> gagnés · réglé aux vrais rapports PMU</span>
                  <span className="inline-flex items-center gap-1 text-emerald-600 font-semibold"><span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" /> temps réel</span>
                </div>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ═══════════ CE QUE VOUS OBTENEZ ═══════════ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Target className="h-3.5 w-3.5" /> Ce que vous obtenez
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Pourquoi nos analyses{" "}
                <span className="text-gradient">tapent juste</span>
              </h2>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 lg:auto-rows-fr">
            <ScrollReveal className="lg:col-span-2 lg:row-span-2">
              <div className="glass-card bento-feature rounded-3xl h-full p-8 flex flex-col">
                <div className="icon-box h-14 w-14 rounded-2xl flex items-center justify-center mb-5"
                  style={{ background: "#FFFBEB", border: "1px solid rgba(217,119,6,0.2)" }}>
                  <FEATURE_MAIN.icon className="h-7 w-7" style={{ color: "#D97706" }} strokeWidth={2} />
                </div>
                <h3 className="font-display text-2xl font-bold text-gray-900 mb-3 leading-snug">{FEATURE_MAIN.title}</h3>
                <p className="text-gray-500 leading-relaxed mb-6 max-w-lg">{FEATURE_MAIN.desc}</p>
                <div className="mt-auto grid sm:grid-cols-2 gap-3.5">
                  {FEATURE_MAIN.categories.map((cat) => (
                    <div key={cat.label} className="rounded-2xl bg-white/70 border border-amber-100 p-3.5">
                      <div className="text-[11px] font-bold uppercase tracking-wide text-brand-gold-deep mb-2">{cat.label}</div>
                      <ul className="space-y-1.5">
                        {cat.items.map((it) => (
                          <li key={it} className="flex items-start gap-2 text-xs text-gray-700 leading-snug">
                            <Check className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-emerald-600" />
                            <span>{it}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            </ScrollReveal>

            {FEATURES.map((f, i) => (
              <ScrollReveal key={f.title} delay={i * 70}>
                <div className="glass-card tilt-card rounded-3xl h-full p-6">
                  <div className="icon-box h-11 w-11 rounded-xl flex items-center justify-center mb-4"
                    style={{ background: f.bg, border: `1px solid ${f.border}` }}>
                    <f.icon className="h-5 w-5" style={{ color: f.color }} strokeWidth={2} />
                  </div>
                  <h3 className="font-semibold text-gray-900 text-[15px] leading-snug mb-2">{f.title}</h3>
                  <p className="text-[13px] text-gray-500 leading-relaxed">{f.desc}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ═══════════ POUR QUI ═══════════ */}
      <section id="pour-qui" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Users className="h-3.5 w-3.5" /> Pour qui
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Trois façons de jouer,{" "}
                <span className="text-gradient">un outil pour chacune</span>
              </h2>
              <p className="text-gray-500 text-sm mt-3 max-w-2xl mx-auto">
                On ne vend pas le même produit au joueur du dimanche et à celui qui suit six réunions par jour.
                Repérez-vous ci-dessous : la formule adaptée est indiquée.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-5">
            {[
              {
                icon: Search,
                titre: "Vous voulez d'abord vérifier",
                profil: "Le sceptique — et il a raison de l'être",
                points: [
                  "Le palmarès complet est public, course par course",
                  "Programme du jour et cotes accessibles sans payer",
                  "1 pronostic par jour pour juger sur pièces",
                ],
                plan: "Découverte · 0€",
                href: "/inscription",
              },
              {
                icon: Calculator,
                titre: "Vous jouez le week-end",
                profil: "Deux ou trois réunions, un budget défini",
                points: [
                  "5 pronostics par jour, largement de quoi couvrir un samedi",
                  "Le calculateur répartit votre mise au lieu de tout mettre sur un cheval",
                  "Alertes quand un pari de valeur sort sur vos courses",
                ],
                plan: "Standard · 12€/mois",
                href: "/inscription?plan=standard",
                populaire: false,
              },
              {
                icon: Zap,
                titre: "Vous jouez sérieusement",
                profil: "Tous les jours, avec un capital à faire tourner",
                points: [
                  "Pronostics illimités et paris de valeur en temps réel",
                  "Créateur de stratégies : 30+ filtres, testés sur l'historique",
                  "Suivi du capital réglé aux rapports officiels, export des données",
                ],
                plan: "Expert · 19€/mois",
                href: "/inscription?plan=expert",
                populaire: true,
              },
            ].map((p, i) => (
              <ScrollReveal key={p.titre} delay={i * 90}>
                <div className={`rounded-3xl h-full p-6 flex flex-col ${p.populaire ? "bg-white border-2 border-amber-300 shadow-md" : "bg-white border border-gray-200 shadow-sm tilt-card"}`}>
                  <div className="icon-box h-11 w-11 rounded-xl flex items-center justify-center mb-4"
                    style={{ background: "#FFFBEB", border: "1px solid rgba(180,83,9,0.16)" }}>
                    <p.icon className="h-5 w-5 text-brand-gold-deep" strokeWidth={2} />
                  </div>
                  <h3 className="font-display text-lg font-bold text-gray-900 leading-snug">{p.titre}</h3>
                  <p className="text-xs text-gray-500 mt-1">{p.profil}</p>
                  <ul className="mt-4 space-y-2 flex-1">
                    {p.points.map((pt) => (
                      <li key={pt} className="flex items-start gap-2 text-[13px] text-gray-600 leading-snug">
                        <Check className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-emerald-600" /> {pt}
                      </li>
                    ))}
                  </ul>
                  <Link href={p.href}
                    className="press mt-5 inline-flex items-center justify-center gap-1.5 rounded-xl border border-gray-300 px-4 py-2.5 text-sm font-semibold text-gray-700 transition-all hover:border-brand-gold/40 hover:bg-amber-50 hover:text-brand-gold-deep">
                    {p.plan} <ChevronRight className="h-4 w-4" />
                  </Link>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════ PRICING ═══════════ */}
      <section id="tarifs" className="py-24 bg-brand-warm scroll-mt-20">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Sparkles className="h-3.5 w-3.5" /> Tarifs
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-3">
                Moins cher qu&apos;un{" "}
                <span className="text-gradient">ticket perdu par semaine</span>
              </h2>
              <p className="text-gray-500 max-w-xl mx-auto">
                7 jours d&apos;essai gratuit, sans prélèvement avant son terme. Le palmarès, lui, reste public — vous pouvez
                juger avant de payer.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-6 items-start">
            {PLANS.map((plan, i) => (
              <ScrollReveal key={plan.name} delay={i * 100}>
                <div className={`relative rounded-3xl p-7 h-full ${plan.popular ? "plan-popular bg-white border border-amber-300 md:-translate-y-2" : "bg-white border border-gray-200 shadow-sm tilt-card"}`}>
                  {plan.badge && (
                    <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                      <span className="inline-block text-xs bg-gradient-gold text-white font-bold px-4 py-1 rounded-full shadow-md shadow-amber-400/30">{plan.badge}</span>
                    </div>
                  )}
                  <div className="mb-6 mt-1">
                    <h3 className="font-display text-xl font-bold text-gray-900 mb-0.5">{plan.name}</h3>
                    <p className="text-xs text-gray-500 mb-4">{plan.desc}</p>
                    <div className="flex items-baseline gap-1">
                      <span className={`num-display text-4xl font-extrabold ${plan.popular ? "text-brand-gold-deep" : "text-gray-900"}`}>{plan.price}</span>
                      <span className="text-gray-500 text-sm">{plan.period}</span>
                    </div>
                  </div>
                  <ul className="space-y-2.5 mb-8">
                    {plan.features.map((f) => (
                      <li key={f} className="flex items-start gap-2.5 text-sm">
                        <Check className="h-4 w-4 text-emerald-600 mt-0.5 flex-shrink-0" />
                        <span className="text-gray-600">{f}</span>
                      </li>
                    ))}
                  </ul>
                  <Link href={plan.href}
                    className={`press flex items-center justify-center gap-1.5 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${plan.popular ? "btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white shadow-md shadow-amber-400/25" : "border border-gray-300 text-gray-700 hover:border-brand-gold/40 hover:text-brand-gold-deep hover:bg-amber-50"}`}>
                    {plan.cta} <ChevronRight className="h-4 w-4" />
                  </Link>
                </div>
              </ScrollReveal>
            ))}
          </div>
          <p className="text-center text-xs text-gray-500 mt-8">
            -20% avec l&apos;abonnement annuel · Paiement sécurisé Stripe · Annulation à tout moment
          </p>
        </div>
      </section>

      {/* ═══════════ FAQ (+ données structurées FAQPage) ═══════════
          Les questions posées ici sont celles qui bloquent réellement une
          inscription — y compris « est-ce que je vais gagner ? », à laquelle on
          répond non. Le JSON-LD reprend EXACTEMENT le texte visible : Google
          déclasse les FAQ dont le balisage ne correspond pas au contenu affiché. */}
      <section id="faq" className="py-24 bg-white scroll-mt-20">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-10">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Shield className="h-3.5 w-3.5" /> Questions fréquentes
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Les réponses{" "}
                <span className="text-gradient">sans détour</span>
              </h2>
            </div>
          </ScrollReveal>

          <div className="space-y-3">
            {FAQ.map((f, i) => (
              <ScrollReveal key={f.q} delay={i * 60}>
                <details className="group rounded-2xl border border-gray-200 bg-white px-5 py-4 open:border-amber-300 open:bg-amber-50/30">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-gray-900 marker:content-none">
                    {f.q}
                    <ChevronRight className="h-4 w-4 shrink-0 text-brand-gold-deep transition-transform group-open:rotate-90" />
                  </summary>
                  <p className="mt-3 text-sm leading-6 text-gray-600">{f.r}</p>
                </details>
              </ScrollReveal>
            ))}
          </div>

          <p className="mt-8 text-center text-sm text-gray-500">
            Une autre question ?{" "}
            <Link href="/tarifs" className="font-semibold text-brand-gold-deep underline-offset-4 hover:underline">
              Voir le détail des formules
            </Link>
          </p>
        </div>
      </section>

      {/* ═══════════ CTA FINALE — photo ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/cta.jpg" width={1600} height={1064} alt="Arrivée d'une course devant le public" className="absolute inset-0 h-full w-full object-cover ken-burns" />
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
            <p className="text-gray-200/90 text-lg mb-10 max-w-xl mx-auto">
              Des analyses chiffrées et vérifiées sur les vrais résultats du PMU. Essayez BlackTurf
              7 jours, sans engagement : annulez avant la fin de l&apos;essai et rien ne vous est prélevé.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button size="xl" asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-900/40">
                <Link href="/inscription">Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" /></Link>
              </Button>
              <Button variant="outline" size="xl" asChild
                className="press border-white/30 bg-white/5 text-white hover:bg-white/15 hover:border-white/50">
                <Link href="#tarifs">Voir les tarifs</Link>
              </Button>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ═══════════ JEU RESPONSABLE ═══════════ */}
      <section className="py-8 border-t border-gray-100 bg-brand-warm">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <p className="text-xs text-gray-500 leading-relaxed inline-flex flex-wrap items-center justify-center gap-x-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-gray-500 inline" />
            <span><strong className="text-gray-600">Jeu responsable.</strong> BlackTurf est un outil d&apos;aide à la décision,
            pas une garantie de gain. Les performances passées ne préjugent pas des performances futures.
            Interdit aux mineurs. En cas de difficulté :{" "}
            <a href="https://www.joueurs-info-service.fr" target="_blank" rel="noopener noreferrer" className="underline hover:text-gray-600 transition-colors">joueurs-info-service.fr</a>
            {" "}— <strong className="text-gray-600">09 74 75 13 13</strong> (gratuit, 7j/7, 8h-2h).</span>
          </p>
        </div>
      </section>

      <Footer />
    </div>
  );
}
