import Link from "next/link";
import {
  ArrowRight, TrendingUp, Zap, Shield, Trophy,
  Bell, Calculator, ChevronRight, Check, Target,
  Sparkles, Database, AlertTriangle, BarChart3, Wallet, Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { ScrollReveal } from "@/components/ui/ScrollReveal";
import { LiveTicker } from "@/components/ui/LiveTicker";
import { CalculatorDemo } from "@/components/home/CalculatorDemo";
import { LivePalmares } from "@/components/home/LivePalmares";

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
const CAPITAL_DEMO = [
  { type: "Couplé Placé", chevaux: "2 · 4", won: true, pnl: "+14€" },
  { type: "Placé", chevaux: "N°6", won: false, pnl: "−2€" },
  { type: "2 sur 4", chevaux: "1 · 3 · 5 · 8", won: true, pnl: "+24€" },
  { type: "Couplé Gagnant", chevaux: "4 · 7", won: false, pnl: "−2€" },
];

const ICON_GOLD = { color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.16)" };
const FEATURE_MAIN = {
  icon: Target,
  title: "80 critères passés au crible pour chaque cheval",
  desc: "Forme récente, terrain, distance, jockey et entraîneur, confrontations directes, mouvements de cotes… BlackTurf croise tout ce que le marché regarde — et ce qu'il oublie — puis se recale sur l'arrivée réelle après chaque réunion.",
  points: ["Forme & régularité", "Terrain & distance", "Confrontations directes", "Mouvements de cotes"],
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
  { name: "Standard", price: "19€", period: "/mois", desc: "L'essentiel pour parier mieux", badge: "Populaire",
    features: ["5 pronostics/jour", "Top 3 paris de valeur (délai 15 min)", "Calculateur de mise", "Suivi du capital + statistiques", "Alertes push & e-mail", "Historique des résultats"],
    cta: "Essayer 7 jours gratuit", href: "/inscription?plan=standard", popular: true },
  { name: "Expert", price: "39€", period: "/mois", desc: "Pour les parieurs sérieux",
    features: ["Pronostics illimités", "Paris de valeur en temps réel ★★★★", "Calculateur de mise avancé", "Assistant illimité", "Performances détaillées par discipline", "Créateur de stratégies 30+ filtres", "Export des données"],
    cta: "Passer Expert", href: "/inscription?plan=expert", popular: false },
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
  by_discipline: Array<{ discipline: string; nb_courses: number; accuracy_top3: number }>;
  by_day: Array<{ jour: string; accuracy_top3: number; nb_predictions: number }>;
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

async function fetchCoursesAnalysees(): Promise<number | null> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/public`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    const d = await res.json();
    return numOf(d?.nb_courses_analysees);
  } catch { return null; }
}

export default async function HomePage() {
  const [tr, coursesAnalysees] = await Promise.all([fetchTrackRecord(), fetchCoursesAnalysees()]);
  const fmtPct = (x: number | null, dec = 1) => (x == null ? "—" : `${x.toFixed(dec).replace(".", ",")}%`);
  const fmtInt = (x: number | null) => (x == null ? "—" : x.toLocaleString("fr-FR"));

  return (
    <div className="flex flex-col min-h-screen bg-brand-warm">
      <Navbar />

      {/* ═══════════ HERO CINÉMATIQUE (1ʳᵉ section) ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950 min-h-[88vh] flex items-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/hero.jpg" alt="Départ d'une course de chevaux aux portes numérotées"
          className="absolute inset-0 h-full w-full object-cover object-center ken-burns cine-fade" />
        <div className="absolute inset-0 bg-gradient-to-r from-gray-950 via-gray-950/85 to-gray-950/30" />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950/95 via-transparent to-gray-950/40" />

        <div className="relative mx-auto max-w-6xl w-full px-4 sm:px-6 lg:px-8 pt-28 pb-16">
          <div className="max-w-2xl cine-fade">
            <span className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-amber-300 mb-6">
              <span className="live-dot inline-block w-2 h-2 rounded-full bg-amber-400" />
              Pronostics hippiques PMU · paris de valeur
            </span>

            <h1 className="font-display text-[2.6rem] sm:text-6xl font-extrabold tracking-tight leading-[1.03] text-white">
              Le PMU,{" "}
              <span className="text-gradient-animated">version méthode.</span>
            </h1>

            <p className="mt-6 text-lg sm:text-xl text-gray-200/90 leading-relaxed max-w-xl">
              BlackTurf analyse chaque course, repère les paris où la cote{" "}
              <span className="font-semibold text-white">sous-estime</span> les chances, et vous donne un{" "}
              <span className="font-semibold text-white">plan de mise adapté à votre profil</span>.
              Vous pariez avec des chiffres — plus au hasard.
            </p>

            {/* Les 3 piliers = le but du site, compris en 1 coup d'œil */}
            <div className="mt-7 grid grid-cols-1 sm:grid-cols-3 gap-2.5 max-w-xl">
              {[
                { icon: Search, t: "On analyse", d: "80 critères / cheval" },
                { icon: Zap, t: "On détecte la valeur", d: "cote vs vraie chance" },
                { icon: Wallet, t: "Vous misez malin", d: "plan selon votre risque" },
              ].map((p) => (
                <div key={p.t} className="rounded-xl bg-white/10 backdrop-blur-md border border-white/15 px-3.5 py-3">
                  <p.icon className="h-4 w-4 text-amber-300 mb-1.5" />
                  <div className="text-sm font-bold text-white leading-tight">{p.t}</div>
                  <div className="text-[11px] text-gray-300 mt-0.5">{p.d}</div>
                </div>
              ))}
            </div>

            <div className="mt-8 flex flex-col sm:flex-row gap-3">
              <Button size="xl" asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-900/40">
                <Link href="/inscription">Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" /></Link>
              </Button>
              <Button variant="outline" size="xl" asChild
                className="press border-white/30 bg-white/5 text-white hover:bg-white/15 hover:border-white/50">
                <Link href="/programme">Voir le programme du jour</Link>
              </Button>
            </div>

            {/* Stat chips RÉELLES */}
            <div className="mt-8 flex flex-wrap gap-3">
              {[
                { v: fmtPct(tr?.accuracy_top3 ?? null), l: "Précision Top-3", c: "text-amber-300" },
                { v: fmtPct(tr?.favori_place_rate ?? null), l: "Favori placé", c: "text-emerald-300" },
                { v: coursesAnalysees == null ? "—" : `${fmtInt(coursesAnalysees)}+`, l: "Courses analysées", c: "text-white" },
              ].map((s) => (
                <div key={s.l} className="float-chip rounded-2xl bg-white/10 backdrop-blur-md border border-white/15 px-4 py-2.5">
                  <div className={`num-display text-xl font-extrabold ${s.c}`}>{s.v}</div>
                  <div className="text-[10px] uppercase tracking-wide text-gray-300">{s.l}</div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[11px] text-gray-400">Chiffres réels, mesurés sur les arrivées PMU officielles. Sans carte bancaire · annulation à tout moment.</p>
          </div>
        </div>
      </section>

      <LiveTicker />

      {/* ═══════════ PRONOSTICS PAR PROFIL DE RISQUE (vrai outil) ═══════════ */}
      <section className="py-24 bg-white">
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
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-wider text-white bg-brand-gold-deep rounded px-1.5 py-0.5">{EXAMPLE.hippo}</span>
                  <span className="text-xs text-gray-400 font-mono">{EXAMPLE.code} · {EXAMPLE.disc}</span>
                </div>
                <div className="mt-3 space-y-1.5">
                  {EXAMPLE_PICKS.map((h) => (
                    <div key={h.rank} className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${h.rank === 1 ? "bg-amber-50 ring-1 ring-amber-200" : "bg-gray-50"}`}>
                      <span className={`num-display text-xs font-black w-7 ${h.rank === 1 ? "text-brand-gold-deep" : "text-gray-400"}`}>N°{h.num}</span>
                      <span className="text-sm font-medium text-gray-900 flex-1 truncate">{h.nom}</span>
                      <span className="num-display text-xs font-bold text-gray-700 w-9 text-right">{h.p}%</span>
                      <span className="text-[11px] font-mono text-gray-500 w-8 text-right">{h.cote}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 font-semibold text-emerald-700"><Zap className="h-3 w-3" /> Valeur ★★★ détectée</span>
                  <span className="text-gray-400">EV <span className="num-display font-bold text-emerald-600">+14,2%</span></span>
                </div>
              </div>
            </ScrollReveal>

            {/* Portrait photo */}
            <ScrollReveal className="lg:col-span-2" delay={80}>
              <div className="relative rounded-2xl overflow-hidden h-full min-h-[220px]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/portrait.jpg" alt="Cheval et jockey en tête de course" className="absolute inset-0 h-full w-full object-cover ken-burns" />
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
                  <p className="mt-3 text-[10px] text-gray-400">Gain potentiel si le pari est gagnant.</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
          <p className="mt-6 text-center text-[11px] text-gray-400 max-w-2xl mx-auto">
            Exemple illustratif sur une course type. Les paris et gains varient selon la course, votre mise et les
            rapports PMU réels. Parier comporte un risque de perte.
          </p>
        </div>
      </section>

      {/* ═══════════ BANDEAU CINÉMATIQUE ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/showcase.jpg" alt="Peloton de chevaux en pleine course" className="absolute inset-0 h-full w-full object-cover ken-burns" />
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
            <img src="/img/duel.jpg" alt="Duel de chevaux à l'arrivée" className="tilt-card w-full h-40 object-cover rounded-2xl ring-1 ring-white/20 shadow-2xl" />
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
              <div className="glass-card rounded-3xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <span className="eyebrow text-amber-700 text-[10px] font-bold"><Zap className="h-3 w-3" /> Pari de valeur détecté</span>
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>
                <div className="flex items-center gap-3 rounded-2xl bg-amber-50 ring-1 ring-amber-200 px-4 py-3">
                  <span className="num-display text-lg font-black text-brand-gold-deep">N°7</span>
                  <div className="flex-1">
                    <div className="font-semibold text-gray-900">Vent d'Est</div>
                    <div className="text-[11px] text-gray-500">cote 8,5 · {EXAMPLE.hippo}</div>
                  </div>
                  <span className="text-[11px] font-bold text-emerald-600">★★★</span>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-xl bg-gray-50 p-3">
                    <div className="num-display text-lg font-extrabold text-gray-900">19%</div>
                    <div className="text-[10px] text-gray-400 mt-0.5">Proba modèle</div>
                  </div>
                  <div className="rounded-xl bg-gray-50 p-3">
                    <div className="num-display text-lg font-extrabold text-gray-400">12%</div>
                    <div className="text-[10px] text-gray-400 mt-0.5">Proba marché</div>
                  </div>
                  <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-100 p-3">
                    <div className="num-display text-lg font-extrabold text-emerald-600">+14%</div>
                    <div className="text-[10px] text-emerald-700/70 mt-0.5">Valeur (EV)</div>
                  </div>
                </div>
                <p className="mt-4 text-xs text-gray-500 leading-relaxed">
                  À 8,5, le marché lui donne ~12% de chances ; le modèle en voit 19%. La cote paie plus que le risque réel.
                </p>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ═══════════ GESTION DU CAPITAL (vrai outil, image) ═══════════ */}
      <section className="relative py-24 overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/value.jpg" alt="Chevaux sur la piste au soleil couchant" className="absolute inset-0 h-full w-full object-cover ken-burns opacity-40" />
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
                  <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                </div>
                <div className="space-y-1.5">
                  {CAPITAL_DEMO.map((b, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs">
                      <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${b.won ? "bg-emerald-500" : "bg-gray-300"}`} />
                      <span className="font-semibold text-gray-800 flex-1 truncate">{b.type} <span className="font-mono font-normal text-gray-400">{b.chevaux}</span></span>
                      <span className={`num-display font-bold tabular-nums ${b.won ? "text-emerald-600" : "text-gray-400"}`}>{b.pnl}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between text-xs">
                  <span className="text-gray-500">Chaque pari réglé aux <span className="font-semibold text-gray-700">vrais rapports PMU</span></span>
                  <span className="text-emerald-600 font-semibold">temps réel</span>
                </div>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ═══════════ PREUVES RÉELLES (track-record) ═══════════ */}
      <section className="py-24 bg-brand-warm">
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
                Chaque pronostic est confronté à l'arrivée officielle PMU. Voici la précision réelle de
                BlackTurf, mesurée sur les courses déjà réglées — pas une simulation.
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
                  <p className="text-xs text-gray-400 mt-0.5">{m.sub}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>

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
                            <span className="text-gray-400 font-normal ml-1.5">· {d.nb_courses} courses</span>
                          </span>
                        </div>
                        <div className="relative h-3 rounded-full bg-gray-100 overflow-hidden">
                          <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(d.accuracy_top3, 100)}%`, background: "linear-gradient(90deg,#D97706,#F59E0B)" }} />
                          {/* repère 33% (hasard) */}
                          <div className="absolute top-0 bottom-0 w-px bg-gray-500/40" style={{ left: "33%" }} />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-5 flex items-center gap-1.5 text-[11px] text-gray-400">
                    <span className="inline-block w-px h-3 bg-gray-400/60" /> Repère « hasard » à 33 % · au-delà = l&apos;analyse fait mieux.
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
                    <span className="text-[11px] text-gray-400">moy. <span className="num-display font-bold text-gray-700">{avg.toFixed(0)}%</span></span>
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
                      <span key={d.jour} className="flex-1 text-center text-[9px] text-gray-400">{d.jour}</span>
                    ))}
                  </div>
                  <p className="mt-4 text-[11px] text-gray-400">Jour par jour, sur les pronostics réglés aux arrivées PMU officielles.</p>
                </div>
              </ScrollReveal>
              );
            })()}
          </div>

          <p className="mt-6 text-center text-[11px] text-gray-400 max-w-2xl mx-auto leading-relaxed">
            La précision d'analyse mesure la qualité du classement des chevaux. Ce n'est ni un taux de
            gain, ni une garantie de profit. Les performances passées ne préjugent pas des performances futures.
          </p>
        </div>
      </section>

      {/* ═══════════ PALMARÈS EN DIRECT (paris gagnés réels) ═══════════ */}
      <LivePalmares />

      <div className="section-divider" />

      {/* ═══════════ COMMENT ÇA MARCHE ═══════════ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-2">
                <Zap className="h-3.5 w-3.5" /> Comment ça marche
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">3 gestes, moins de 10 secondes</h2>
            </div>
          </ScrollReveal>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { step: "01", title: "Choisissez votre course", desc: "Le programme PMU du jour, déjà analysé. Un score de confiance 0-100 par course." },
              { step: "02", title: "Entrez votre mise", desc: "Indiquez le montant. Le plan se répartit : sécurité, rendement, coup — selon votre profil." },
              { step: "03", title: "Pariez, puis suivez", desc: "BlackTurf règle les résultats réels et met votre rendement à jour, course après course." },
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

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 auto-rows-fr">
            <ScrollReveal className="lg:col-span-2 lg:row-span-2">
              <div className="glass-card bento-feature rounded-3xl h-full p-8 flex flex-col">
                <div className="icon-box h-14 w-14 rounded-2xl flex items-center justify-center mb-5"
                  style={{ background: "#FFFBEB", border: "1px solid rgba(217,119,6,0.2)" }}>
                  <FEATURE_MAIN.icon className="h-7 w-7" style={{ color: "#D97706" }} strokeWidth={2} />
                </div>
                <h3 className="font-display text-2xl font-bold text-gray-900 mb-3 leading-snug">{FEATURE_MAIN.title}</h3>
                <p className="text-gray-500 leading-relaxed mb-6 max-w-lg">{FEATURE_MAIN.desc}</p>
                <div className="mt-auto grid grid-cols-2 gap-3">
                  {FEATURE_MAIN.points.map((p) => (
                    <div key={p} className="flex items-center gap-2 rounded-xl bg-white/70 border border-amber-100 px-3 py-2.5">
                      <Check className="h-4 w-4 flex-shrink-0 text-brand-gold-deep" />
                      <span className="text-xs font-semibold text-gray-700">{p}</span>
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

      {/* ═══════════ CALCULATEUR ═══════════ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <ScrollReveal direction="right" className="order-2 lg:order-1">
              <div className="glass-card rounded-3xl p-2">
                <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
                  <Calculator className="h-4 w-4 text-brand-gold-deep" />
                  <span className="text-xs font-semibold text-gray-700">Calculateur de mise</span>
                  <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">Démo</span>
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

      <div className="section-divider" />

      {/* ═══════════ PRICING ═══════════ */}
      <section className="py-24 bg-brand-warm" id="tarifs">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Sparkles className="h-3.5 w-3.5" /> Tarifs
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-3">Simples et transparents</h2>
              <p className="text-gray-500">7 jours d&apos;essai gratuit, sans carte bancaire.</p>
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
          <p className="text-center text-xs text-gray-400 mt-8">
            -20% avec l&apos;abonnement annuel · Paiement sécurisé Stripe · Annulation à tout moment
          </p>
        </div>
      </section>

      {/* ═══════════ CTA FINALE — photo ═══════════ */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/cta.jpg" alt="Arrivée d'une course devant le public" className="absolute inset-0 h-full w-full object-cover ken-burns" />
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
              7 jours, sans engagement et sans carte bancaire.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button size="xl" asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-900/40">
                <Link href="/inscription">Essai gratuit 7 jours — sans CB <ArrowRight className="h-5 w-5 ml-1" /></Link>
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
          <p className="text-xs text-gray-400 leading-relaxed inline-flex flex-wrap items-center justify-center gap-x-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-gray-400 inline" />
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
