import Link from "next/link";
import type { CSSProperties } from "react";
import {
  ArrowRight, TrendingUp, Zap, Shield, Brain,
  Clock, Calculator, ChevronRight, Check, Sparkles,
  Gauge, Activity, BarChart3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { ScrollReveal } from "@/components/ui/ScrollReveal";
import { LiveTicker } from "@/components/ui/LiveTicker";

const FEATURES = [
  {
    icon: Calculator,
    title: "Calculateur de mise personnalisé",
    desc: "Entrez votre montant → BlackTurf génère votre plan de pari sur mesure : sécurité, rendement, coup. Adapté à votre profil de risque.",
    badge: "Exclusif",
    color: "#D97706",
    bg: "#FFFBEB",
    borderColor: "rgba(217,119,6,0.2)",
    featured: true,
  },
  {
    icon: Brain,
    title: "IA d'ensemble XGBoost + LightGBM + CatBoost",
    desc: "3 modèles combinés. 80+ variables par partant. Calibration isotonique (Brier < 0.18). ELO 4 dimensions.",
    color: "#7C3AED",
    bg: "#F5F3FF",
    borderColor: "rgba(124,58,237,0.15)",
  },
  {
    icon: Zap,
    title: "Paris de valeur en temps réel",
    desc: "Espérance (EV) = (Cote × Proba) − 1. Détection automatique 4 niveaux ★. Triangulation PMU / Geny / BZH. Indicateur d'afflux de mises.",
    color: "#059669",
    bg: "#ECFDF5",
    borderColor: "rgba(5,150,105,0.15)",
  },
  {
    icon: TrendingUp,
    title: "Critère de Kelly & Capital",
    desc: "Mise optimale calculée automatiquement. Demi-Kelly, plafond 5%. Rendement personnel vs rendement du modèle en temps réel.",
    color: "#2563EB",
    bg: "#EFF6FF",
    borderColor: "rgba(37,99,235,0.15)",
  },
  {
    icon: Shield,
    title: "ELO hippique 4 dimensions",
    desc: "Scores ELO global / plat / trot / obstacle. ELO de progression (vitesse d'évolution). Mis à jour après chaque course.",
    color: "#D97706",
    bg: "#FFFBEB",
    borderColor: "rgba(217,119,6,0.15)",
  },
  {
    icon: Clock,
    title: "Alertes & Assistant IA",
    desc: "Claude API intégré. Push VAPID, email, in-app. Digest matinal. Posez vos questions en langage naturel.",
    color: "#0891B2",
    bg: "#ECFEFF",
    borderColor: "rgba(8,145,178,0.15)",
  },
];

const PLANS = [
  {
    name: "Découverte",
    price: "0€",
    period: "/mois",
    desc: "Découvrez la plateforme",
    features: [
      "Programme du jour",
      "Cotes publiques",
      "1 prédiction/jour",
      "Statistiques publiques du modèle",
    ],
    cta: "Commencer gratuitement",
    href: "/inscription",
    popular: false,
  },
  {
    name: "Standard",
    price: "19€",
    period: "/mois",
    desc: "L'essentiel pour gagner",
    badge: "Populaire",
    features: [
      "5 prédictions/jour",
      "Top 3 paris de valeur (délai 15 min)",
      "Calculateur de mise standard",
      "Suivi du capital + statistiques",
      "Alertes push & e-mail",
      "Test sur historique 7 jours",
    ],
    cta: "Essayer 7 jours gratuit",
    href: "/inscription?plan=standard",
    popular: true,
  },
  {
    name: "Expert",
    price: "39€",
    period: "/mois",
    desc: "Pour les parieurs sérieux",
    features: [
      "Prédictions illimitées",
      "Paris de valeur en temps réel ★★★★",
      "Calculateur Kelly avancé",
      "Assistant IA illimité",
      "Test sur historique 365 jours",
      "Créateur de stratégies 30+ filtres",
      "Export des données + API",
    ],
    cta: "Passer Expert",
    href: "/inscription?plan=expert",
    popular: false,
  },
];

// Placeholders HONNÊTES si l'API stats est indisponible : on n'invente AUCUN chiffre
// (règle d'intégrité). "—" = inconnu, jamais une valeur marketing fabriquée.
const STATIC_STATS = {
  auc_roc: "—",
  roi_simule_6mois: "—",
  nb_courses_analysees: "—",
  nb_utilisateurs: "—",
  precision_top3: "—",
};

async function fetchStats() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/public`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

async function fetchEquityCurve() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/equity-curve`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

export default async function HomePage() {
  const [apiStats, curveData] = await Promise.allSettled([fetchStats(), fetchEquityCurve()]);

  // Mapping HONNÊTE : toute valeur nulle/absente devient "—" (jamais "+null%" ni 0 factice)
  const v = apiStats.status === "fulfilled" && apiStats.value ? apiStats.value : null;
  const has = (x: unknown) => x !== null && x !== undefined && !(typeof x === "number" && Number.isNaN(x));
  const stats = v
    ? {
        auc_roc: has(v.auc_roc) ? String(v.auc_roc) : "—",
        roi_simule_6mois: has(v.roi_simule_6mois) ? `+${String(v.roi_simule_6mois).replace(".", ",")}%` : "—",
        nb_courses_analysees: has(v.nb_courses_analysees) ? Number(v.nb_courses_analysees).toLocaleString("fr-FR") + "+" : "—",
        nb_utilisateurs: has(v.nb_utilisateurs) ? String(v.nb_utilisateurs) : "—",
        precision_top3: has(v.precision_top3) ? `${Math.round(v.precision_top3 * 100)}%` : "—",
      }
    : STATIC_STATS;

  // Courbe RÉELLE uniquement (backtest 10€ sur value bets ★★★+ + vrais résultats).
  // Si pas assez d'historique réel, on N'AFFICHE PAS de courbe fabriquée (intégrité)
  // → état "en construction".
  const isCurveReal = curveData.status === "fulfilled" && curveData.value?.is_real
    && Array.isArray(curveData.value.points) && curveData.value.points.length >= 10;
  const BACKTEST_CURVE = isCurveReal
    ? curveData.value.points.map((p: { date: string; bankroll: number }) => ({ m: p.date.slice(5, 7), k: p.bankroll }))
    : [];
  const maxK = BACKTEST_CURVE.length ? Math.max(...BACKTEST_CURVE.map((d: { m: string; k: number }) => d.k)) : 0;
  const minK = BACKTEST_CURVE.length ? Math.min(...BACKTEST_CURVE.map((d: { m: string; k: number }) => d.k)) : 0;
  const range = maxK - minK;

  const parseStatNum = (v: string) => parseFloat(v.replace(",", ".").replace(/[^0-9.]/g, ""));

  // Valeurs numériques pour les tuiles bento (NaN ⇒ on affiche "—", jamais d'invention)
  const precisionNum = parseStatNum(stats.precision_top3);
  const aucNum = parseStatNum(stats.auc_roc);
  const roiNum = parseStatNum(stats.roi_simule_6mois);
  const coursesNum = parseStatNum(stats.nb_courses_analysees);

  return (
    <div className="flex flex-col min-h-screen bg-brand-warm">
      <Navbar />

      {/* ══ HERO ══ */}
      <section className="relative gradient-hero-v2 min-h-[92vh] flex flex-col justify-center overflow-hidden grid-lines">
        {/* Orbs + particules dorées */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
          <div className="orb-1 absolute top-[-40px] left-1/2 w-[640px] h-[320px] rounded-full bg-amber-400/10 blur-[90px]" />
          <div className="orb-2 absolute bottom-10 right-[8%] w-72 h-72 rounded-full bg-amber-300/10 blur-[70px]" />
          <div className="orb-3 absolute top-1/3 left-[6%] w-48 h-48 rounded-full bg-yellow-400/6 blur-[50px]" />
          {[
            { l: "12%", t: "22%", s: 6, d: "7s", delay: "0s" },
            { l: "82%", t: "18%", s: 8, d: "9s", delay: "1.2s" },
            { l: "68%", t: "70%", s: 5, d: "8s", delay: "0.6s" },
            { l: "28%", t: "78%", s: 7, d: "10s", delay: "2s" },
            { l: "92%", t: "52%", s: 4, d: "7.5s", delay: "1.6s" },
            { l: "44%", t: "12%", s: 5, d: "11s", delay: "0.3s" },
          ].map((p, i) => (
            <span
              key={i}
              className="particle absolute rounded-full bg-amber-400/40"
              style={{ left: p.l, top: p.t, width: p.s, height: p.s, animationDuration: p.d, animationDelay: p.delay }}
            />
          ))}
        </div>

        <div className="relative mx-auto max-w-6xl w-full px-4 sm:px-6 lg:px-8 pt-24 pb-16 sm:pt-28 sm:pb-20">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-10 items-center">

            {/* ── Colonne texte ── */}
            <div className="text-center lg:text-left">
              <div className="flex justify-center lg:justify-start mb-7">
                <span className="badge-pulse eyebrow px-4 py-1.5 rounded-full border border-amber-300/60 bg-white/70 backdrop-blur-sm text-amber-700 text-[11px] font-semibold shadow-sm">
                  <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                  Terminal IA • Analyse hippique en direct
                </span>
              </div>

              <h1 className="font-display text-[2.6rem] sm:text-6xl lg:text-[4.1rem] font-extrabold tracking-tight mb-6 leading-[1.03] text-gray-900">
                Misez avec un{" "}
                <span className="relative inline-block text-gradient-animated">
                  cerveau de pro
                  <svg className="absolute -bottom-2 left-0 w-full" height="10" viewBox="0 0 200 10" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M2 7 Q 50 2 100 6 T 198 5" fill="none" stroke="#F59E0B" strokeWidth="3" strokeLinecap="round" opacity="0.6" />
                  </svg>
                </span>
                <br className="hidden sm:block" /> pas avec votre instinct
              </h1>

              <p className="text-lg sm:text-xl text-gray-600 max-w-xl mx-auto lg:mx-0 mb-3 leading-relaxed">
                Entrez votre mise — l&apos;IA calcule la course, les probabilités réelles et
                votre plan de pari optimal. Mise exacte, gain potentiel, paris de valeur détectés.
              </p>
              <p className="text-[13px] text-gray-400 max-w-lg mx-auto lg:mx-0 mb-9 font-mono tracking-tight">
                XGBoost + LightGBM + CatBoost · 80+ variables · Paris de valeur · Critère de Kelly
              </p>

              {/* CTA */}
              <div className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start">
                <Button
                  size="xl"
                  asChild
                  className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-lg shadow-amber-400/30 transition-all duration-200"
                >
                  <Link href="/inscription">
                    Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" />
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="xl"
                  asChild
                  className="press border-gray-300 text-gray-700 hover:border-brand-gold/50 hover:text-brand-gold-deep hover:bg-amber-50 transition-all"
                >
                  <Link href="/programme">Programme du jour</Link>
                </Button>
              </div>

              {/* Chips de preuve — chiffres RÉELS ("—" si indisponible) */}
              <div className="mt-8 flex flex-wrap justify-center lg:justify-start gap-2.5">
                {[
                  { icon: Gauge, label: "Précision Top-3", value: stats.precision_top3, color: "#D97706" },
                  { icon: BarChart3, label: "Courses analysées", value: stats.nb_courses_analysees, color: "#2563EB" },
                  { icon: Sparkles, label: "AUC modèle", value: stats.auc_roc, color: "#059669" },
                ].map((c) => (
                  <span key={c.label} className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white/80 backdrop-blur-sm px-3 py-1.5 shadow-sm">
                    <c.icon className="h-3.5 w-3.5" style={{ color: c.color }} />
                    <span className="num-display text-sm font-bold" style={{ color: c.color }}>{c.value}</span>
                    <span className="text-[11px] text-gray-500">{c.label}</span>
                  </span>
                ))}
              </div>

              {/* Trust signals */}
              <div className="mt-6 flex flex-wrap justify-center lg:justify-start gap-x-5 gap-y-2 text-xs text-gray-500">
                {["Sans CB requis", "7 jours gratuit", "Annulation à tout moment"].map((t) => (
                  <span key={t} className="flex items-center gap-1.5">
                    <Check className="h-3.5 w-3.5 text-emerald-600" />
                    {t}
                  </span>
                ))}
              </div>
            </div>

            {/* ── Colonne carte "analyse IA" (exemple illustratif) ── */}
            <div className="relative">
              {/* halo */}
              <div className="absolute -inset-6 bg-gradient-to-tr from-amber-300/20 via-transparent to-emerald-300/10 blur-2xl rounded-[2rem] pointer-events-none" aria-hidden="true" />

              <div className="hero-card-float relative">
                <div className="card-scan rounded-3xl border border-amber-200/70 bg-white/95 backdrop-blur-sm p-6 shadow-[0_24px_70px_-20px_rgba(217,119,6,0.35)]">
                  {/* En-tête carte */}
                  <div className="flex items-center justify-between">
                    <span className="eyebrow text-amber-700 text-[10px] font-bold">
                      <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      Analyse IA
                    </span>
                    <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">
                      Exemple
                    </span>
                  </div>

                  {/* Course */}
                  <div className="mt-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
                    <span className="text-base">🏇</span> Deauville
                    <span className="text-gray-400 font-normal">· R4 C5 · Plat 1600m</span>
                  </div>

                  {/* Anneau de confiance */}
                  <div className="mt-5 flex items-center gap-5">
                    <div className="relative h-28 w-28 flex-shrink-0">
                      <svg className="h-28 w-28 -rotate-90" viewBox="0 0 120 120">
                        <circle cx="60" cy="60" r="52" fill="none" stroke="#F3F4F6" strokeWidth="11" />
                        <circle
                          cx="60" cy="60" r="52" fill="none" stroke="url(#confGrad)" strokeWidth="11" strokeLinecap="round"
                          strokeDasharray="326.726"
                          className="ring-anim"
                          style={{ "--c": "326.726", "--off": "71.88", strokeDashoffset: "71.88" } as CSSProperties}
                        />
                        <defs>
                          <linearGradient id="confGrad" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0%" stopColor="#F59E0B" />
                            <stop offset="100%" stopColor="#B45309" />
                          </linearGradient>
                        </defs>
                      </svg>
                      <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <span className="num-display text-3xl font-extrabold text-gray-900">78%</span>
                        <span className="text-[9px] uppercase tracking-wider text-gray-400">Confiance</span>
                      </div>
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-900">Indice de confiance IA</p>
                      <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                        Probabilité que le vainqueur figure dans le Top-3 du modèle pour cette course.
                      </p>
                    </div>
                  </div>

                  {/* Top picks */}
                  <div className="mt-5 space-y-2">
                    {[
                      { rank: 1, nom: "Paladin Noir", cote: "3,4", p: 42, gold: true },
                      { rank: 2, nom: "Royal Flush", cote: "5,1", p: 28, gold: false },
                      { rank: 3, nom: "Vent d'Est", cote: "7,2", p: 19, gold: false },
                    ].map((h, i) => (
                      <div key={h.rank} className={`flex items-center gap-3 rounded-xl px-3 py-2 ${h.gold ? "bg-amber-50 ring-1 ring-amber-200" : "bg-gray-50"}`}>
                        <span className={`num-display text-xs font-black w-5 ${h.gold ? "text-brand-gold-deep" : "text-gray-400"}`}>#{h.rank}</span>
                        <span className="text-sm font-medium text-gray-900 flex-1 truncate">{h.nom}</span>
                        <div className="hidden sm:block w-20 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                          <div
                            className="proba-bar h-full rounded-full"
                            style={{ "--w": `${h.p}%`, "--d": `${0.5 + i * 0.15}s`, background: h.gold ? "linear-gradient(90deg,#D97706,#F59E0B)" : "#9CA3AF" } as CSSProperties}
                          />
                        </div>
                        <span className="num-display text-xs font-bold text-gray-700 w-9 text-right">{h.p}%</span>
                        <span className="text-[11px] font-mono text-gray-500 w-9 text-right">{h.cote}</span>
                      </div>
                    ))}
                  </div>

                  {/* Pari de valeur */}
                  <div className="mt-4 vb-glow flex items-center justify-between rounded-xl bg-gradient-to-r from-emerald-50 to-white border border-emerald-200 px-3 py-2.5">
                    <span className="flex items-center gap-2 text-xs font-semibold text-emerald-700">
                      <Zap className="h-3.5 w-3.5" /> Pari de valeur détecté ★★★
                    </span>
                    <span className="num-display text-sm font-extrabold text-emerald-600">EV +14,2%</span>
                  </div>

                  {/* Plan de mise */}
                  <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-xs">
                    <span className="text-gray-500">Mise <span className="font-semibold text-gray-900">10€</span> sur Paladin Noir</span>
                    <span className="num-display font-bold text-brand-gold-deep">→ 34€ si gagnant</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══ LIVE TICKER ══ */}
      <LiveTicker />

      {/* ══ STATS — BENTO ══ */}
      <section className="py-16 sm:py-20 bg-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-10">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Activity className="h-3.5 w-3.5" /> Chiffres réels
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Une IA qui se mesure, pas qui se vante
              </h2>
              <p className="text-gray-500 text-sm mt-2 max-w-lg mx-auto">
                Données calculées sur des courses passées et vérifiables — aucune valeur fabriquée.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-2 lg:grid-cols-4 auto-rows-[150px] gap-4">

            {/* Tuile vedette — Précision Top-3 (2×2) */}
            <ScrollReveal className="col-span-2 row-span-2" delay={0}>
              <div className="glass-card bento-feature rounded-2xl p-7 h-full flex flex-col justify-between">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">Précision Top-3</p>
                    <p className="text-xs text-gray-500 mt-0.5">Part des courses où le vainqueur est dans le top-3 de l&apos;IA</p>
                  </div>
                  <div className="icon-box h-11 w-11 rounded-xl flex items-center justify-center" style={{ background: "#FFFBEB", border: "1px solid rgba(217,119,6,0.2)" }}>
                    <Gauge className="h-5 w-5" style={{ color: "#D97706" }} />
                  </div>
                </div>

                <div>
                  <div className="num-display text-6xl sm:text-7xl font-extrabold" style={{ color: "#D97706" }}>
                    {Number.isNaN(precisionNum) ? "—" : <AnimatedCounter end={precisionNum} duration={2000} decimals={0} suffix="%" />}
                  </div>
                  {/* Barre comparative vs hasard (33%) */}
                  {!Number.isNaN(precisionNum) && (
                    <div className="mt-4">
                      <div className="relative h-2 rounded-full bg-gray-100 overflow-hidden">
                        <div
                          className="bar-grow absolute inset-y-0 left-0 rounded-full bg-gradient-gold"
                          style={{ "--bar-pct": `${Math.min(precisionNum, 100)}%` } as CSSProperties}
                        />
                        {/* repère 33% aléatoire */}
                        <div className="absolute inset-y-0 w-px bg-gray-400/70" style={{ left: "33%" }} />
                      </div>
                      <div className="flex justify-between mt-1.5 text-[10px] text-gray-400">
                        <span>0%</span>
                        <span className="text-gray-500">33% = hasard</span>
                        <span>100%</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </ScrollReveal>

            {/* AUC-ROC */}
            <ScrollReveal delay={80}>
              <div className="glass-card rounded-2xl p-6 h-full flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">AUC-ROC</p>
                  <Sparkles className="h-4 w-4" style={{ color: "#2563EB" }} />
                </div>
                <div>
                  <div className="num-display text-4xl font-extrabold" style={{ color: "#2563EB" }}>
                    {Number.isNaN(aucNum) ? "—" : <AnimatedCounter end={aucNum} duration={2000} decimals={2} />}
                  </div>
                  <p className="text-[11px] text-gray-400 mt-1">Calibration isotonique · Brier &lt; 0.18</p>
                </div>
              </div>
            </ScrollReveal>

            {/* Rendement simulé */}
            <ScrollReveal delay={160}>
              <div className="glass-card rounded-2xl p-6 h-full flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Rendement 6 mois</p>
                  <TrendingUp className="h-4 w-4" style={{ color: "#059669" }} />
                </div>
                <div>
                  <div className="num-display text-4xl font-extrabold" style={{ color: "#059669" }}>
                    {Number.isNaN(roiNum) ? "—" : <>+<AnimatedCounter end={roiNum} duration={2200} decimals={1} suffix="%" /></>}
                  </div>
                  <p className="text-[11px] text-gray-400 mt-1">10€ fixe / pari de valeur ★★★+</p>
                </div>
              </div>
            </ScrollReveal>

            {/* Courses analysées (2×1) */}
            <ScrollReveal className="col-span-2" delay={240}>
              <div className="glass-card rounded-2xl p-6 h-full flex items-center justify-between">
                <div>
                  <div className="num-display text-4xl sm:text-5xl font-extrabold" style={{ color: "#D97706" }}>
                    {Number.isNaN(coursesNum) ? "—" : <><AnimatedCounter end={coursesNum} duration={2400} decimals={0} />+</>}
                  </div>
                  <p className="text-sm font-semibold text-gray-900 mt-1">Courses analysées</p>
                  <p className="text-[11px] text-gray-400">Données réelles PMU, mises à jour chaque nuit</p>
                </div>
                <div className="icon-box hidden sm:flex h-14 w-14 rounded-2xl items-center justify-center" style={{ background: "#FFFBEB", border: "1px solid rgba(217,119,6,0.2)" }}>
                  <BarChart3 className="h-6 w-6" style={{ color: "#D97706" }} />
                </div>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ HOW IT WORKS ══ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="eyebrow text-amber-800 text-[11px] font-semibold mb-3">
                <Zap className="h-3.5 w-3.5" /> Simple & rapide
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-3">
                Comment BlackTurf fonctionne
              </h2>
              <p className="text-gray-500">3 étapes, moins de 10 secondes</p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-6">
            {[
              {
                step: "01",
                title: "Choisissez votre course",
                desc: "Programme PMU du jour analysé par l'IA. Score de confiance 0-100 visible sur chaque course.",
                color: "#D97706",
                bg: "#FFFBEB",
                border: "rgba(217,119,6,0.2)",
              },
              {
                step: "02",
                title: "Entrez votre mise",
                desc: "Indiquez combien vous voulez miser. Le conseiller calcule instantanément votre plan personnalisé.",
                color: "#059669",
                bg: "#ECFDF5",
                border: "rgba(5,150,105,0.2)",
              },
              {
                step: "03",
                title: "Suivez vos résultats",
                desc: "BlackTurf enregistre les résultats, met à jour votre rendement personnel et améliore ses prédictions.",
                color: "#2563EB",
                bg: "#EFF6FF",
                border: "rgba(37,99,235,0.2)",
              },
            ].map((s, i) => (
              <ScrollReveal key={s.step} delay={i * 100}>
                <div className={`relative h-full ${i < 2 ? "step-connector" : ""}`}>
                  <div className="glass-card rounded-2xl p-7 text-center h-full">
                    <div
                      className="icon-box h-14 w-14 rounded-2xl flex items-center justify-center font-mono font-black text-lg mx-auto mb-5"
                      style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color }}
                    >
                      {s.step}
                    </div>
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

      {/* ══ FEATURES — BENTO ══ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-14">
              <span className="eyebrow text-emerald-800 text-[11px] font-semibold mb-3">
                <Brain className="h-3.5 w-3.5" /> Technologie
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-4">
                L&apos;arsenal du parieur{" "}
                <span className="text-gradient">professionnel</span>
              </h2>
              <p className="text-gray-500 max-w-xl mx-auto">
                Toutes les analyses dont vous avez besoin, automatisées et actualisées en temps réel.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 auto-rows-fr gap-5">
            {FEATURES.map((f, i) => (
              <ScrollReveal key={f.title} delay={i * 70} className={f.featured ? "md:col-span-2 lg:row-span-2" : ""}>
                <div className={`glass-card rounded-2xl h-full ${f.featured ? "bento-feature p-8 flex flex-col" : "p-6"}`}>
                  <div className="flex items-start justify-between mb-4">
                    <div
                      className={`icon-box rounded-xl flex items-center justify-center flex-shrink-0 ${f.featured ? "h-14 w-14" : "h-11 w-11"}`}
                      style={{ background: f.bg, border: `1px solid ${f.borderColor}` }}
                    >
                      <f.icon className={f.featured ? "h-7 w-7" : "h-5 w-5"} style={{ color: f.color }} />
                    </div>
                    {f.badge && (
                      <span className="text-[10px] bg-amber-100 text-amber-800 border border-amber-200 font-semibold px-2 py-0.5 rounded-full">
                        {f.badge}
                      </span>
                    )}
                  </div>
                  <h3 className={`font-semibold text-gray-900 leading-snug ${f.featured ? "text-xl mb-3" : "text-sm mb-2"}`}>{f.title}</h3>
                  <p className={`text-gray-500 leading-relaxed ${f.featured ? "text-sm" : "text-xs"}`}>{f.desc}</p>
                  {f.featured && (
                    <Link href="/programme" className="press mt-auto pt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-gold-deep hover:gap-2.5 transition-all">
                      Voir le calculateur <ArrowRight className="h-4 w-4" />
                    </Link>
                  )}
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ PERFORMANCE ══ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-14">
              <span className="eyebrow text-emerald-800 text-[11px] font-semibold mb-3">
                <Shield className="h-3.5 w-3.5" /> Performances vérifiables
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-3">
                Nos résultats, chiffres réels
              </h2>
              <p className="text-gray-500 text-sm max-w-lg mx-auto">
                Calculés en simulant 10€ fixes sur chaque pari de valeur ★★★+ sur les courses passées.
                Source de vérité : résultats PMU officiels. Mis à jour chaque nuit.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-2 gap-8 items-start">
            {/* Metrics */}
            <ScrollReveal direction="left">
              <div className="space-y-3">
                {[
                  { label: "Rendement simulé 6 mois", value: stats.roi_simule_6mois, sub: "10€ fixes sur paris de valeur ★★★+", color: "#059669" },
                  { label: "Précision Top-3",   value: stats.precision_top3,    sub: "vs 33% pour un choix aléatoire",         color: "#D97706" },
                  { label: "AUC-ROC modèle",    value: stats.auc_roc,           sub: "Calibration isotonique (Brier < 0.18)", color: "#2563EB" },
                  { label: "Courses analysées", value: stats.nb_courses_analysees, sub: "Données historiques vérifiables",   color: "#7C3AED" },
                ].map((m) => (
                  <div
                    key={m.label}
                    className="metric-row flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4 cursor-default shadow-sm"
                  >
                    <div>
                      <p className="text-sm font-semibold text-gray-900">{m.label}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{m.sub}</p>
                    </div>
                    <div className="num-display text-2xl font-extrabold font-mono" style={{ color: m.color }}>
                      {m.value}
                    </div>
                  </div>
                ))}
                <p className="text-[10px] text-gray-400 text-center mt-3 px-2">
                  Statistiques calculées sur des courses PASSÉES et vérifiables.
                  Les résultats PMU officiels sont la source de vérité.
                </p>
              </div>
            </ScrollReveal>

            {/* Equity curve — affichée UNIQUEMENT si historique réel suffisant */}
            <ScrollReveal direction="right">
              <div className="glass-card rounded-2xl p-6 bg-white">
              {!isCurveReal ? (
                <div className="flex flex-col items-center justify-center text-center h-64">
                  <p className="text-sm font-semibold text-gray-900 mb-1">Courbe de performance — en construction</p>
                  <p className="text-xs text-gray-500 max-w-xs">
                    Le backtest réel (10€ par pari de valeur ★★★+) s&apos;affichera dès que
                    l&apos;historique des courses sera suffisant. Aucune courbe fabriquée — uniquement du vérifié.
                  </p>
                </div>
              ) : (
                <>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-semibold text-gray-900">Courbe simulée — Capital 1 000€</p>
                  <span className="text-[10px] font-mono font-bold" style={{ color: "#059669" }}>
                    {(() => {
                      const gain = BACKTEST_CURVE[BACKTEST_CURVE.length - 1].k - 1000;
                      const pct = ((gain / 1000) * 100).toFixed(1);
                      return `${gain >= 0 ? "+" : ""}${pct}%`;
                    })()}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mb-5">10€ fixes par pari de valeur ★★★+ · backtest sur résultats réels</p>
                <div className="relative h-44">
                  <svg viewBox="0 0 400 140" className="w-full h-full" preserveAspectRatio="none">
                    {[0, 1, 2, 3].map(i => (
                      <line key={i} x1="0" y1={i * 46} x2="400" y2={i * 46}
                        stroke="rgba(0,0,0,0.05)" strokeWidth="1" />
                    ))}
                    <defs>
                      <linearGradient id="chartGrad2" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#059669" stopOpacity="0.15" />
                        <stop offset="100%" stopColor="#059669" stopOpacity="0.01" />
                      </linearGradient>
                    </defs>
                    <polygon
                      fill="url(#chartGrad2)"
                      points={[
                        "0,140",
                        ...BACKTEST_CURVE.map((d: { m: string; k: number }, i: number) => {
                          const x = (i / (BACKTEST_CURVE.length - 1)) * 400;
                          const y = 130 - ((d.k - minK) / Math.max(range, 1)) * 110;
                          return `${x},${y}`;
                        }),
                        "400,140",
                      ].join(" ")}
                    />
                    <polyline
                      fill="none"
                      stroke="#059669"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      points={BACKTEST_CURVE.map((d: { m: string; k: number }, i: number) => {
                        const x = (i / (BACKTEST_CURVE.length - 1)) * 400;
                        const y = 130 - ((d.k - minK) / Math.max(range, 1)) * 110;
                        return `${x},${y}`;
                      }).join(" ")}
                    />
                    {(() => {
                      const last = BACKTEST_CURVE[BACKTEST_CURVE.length - 1];
                      const x = 400;
                      const y = 130 - ((last.k - minK) / Math.max(range, 1)) * 110;
                      return (
                        <>
                          <circle cx={x} cy={y} r="8" fill="#059669" fillOpacity="0.15" />
                          <circle cx={x} cy={y} r="4" fill="#059669" />
                        </>
                      );
                    })()}
                  </svg>
                  <div className="flex justify-between text-[9px] text-gray-400 mt-1">
                    {BACKTEST_CURVE.filter((_: { m: string; k: number }, i: number) => i % 3 === 0).map((d: { m: string; k: number }) => (
                      <span key={d.m}>{d.m}</span>
                    ))}
                  </div>
                </div>
                <div className="flex justify-between mt-3 pt-3 border-t border-gray-100">
                  <span className="text-xs text-gray-500">Départ : 1 000€</span>
                  <span className="text-xs font-bold tabular-nums" style={{ color: "#059669" }}>
                    {(() => {
                      const gain = BACKTEST_CURVE[BACKTEST_CURVE.length - 1].k - 1000;
                      const pct = ((gain / 1000) * 100).toFixed(1);
                      return `${gain >= 0 ? "+" : ""}${gain.toFixed(0)}€ (${gain >= 0 ? "+" : ""}${pct}%)`;
                    })()}
                  </span>
                </div>
                </>
              )}
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ PRICING ══ */}
      <section className="py-24 bg-white" id="tarifs">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="eyebrow text-amber-800 text-[11px] font-semibold mb-3">
                <Sparkles className="h-3.5 w-3.5" /> Tarifs
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900 mb-3">Simples et transparents</h2>
              <p className="text-gray-500">7 jours d&apos;essai gratuit sans carte bancaire.</p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-6 items-start">
            {PLANS.map((plan, i) => (
              <ScrollReveal key={plan.name} delay={i * 100}>
                <div
                  className={`relative rounded-2xl p-7 h-full ${
                    plan.popular
                      ? "plan-popular bg-white border border-amber-300 md:-translate-y-2"
                      : "bg-white border border-gray-200 shadow-sm card-hover"
                  }`}
                >
                  {plan.badge && (
                    <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                      <span className="inline-block text-xs bg-gradient-gold text-white font-bold px-4 py-1 rounded-full shadow-md shadow-amber-400/30">
                        {plan.badge}
                      </span>
                    </div>
                  )}

                  <div className="mb-6 mt-1">
                    <h3 className="font-display text-xl font-bold text-gray-900 mb-0.5">{plan.name}</h3>
                    <p className="text-xs text-gray-500 mb-4">{plan.desc}</p>
                    <div className="flex items-baseline gap-1">
                      <span className={`num-display text-4xl font-extrabold ${plan.popular ? "text-brand-gold-deep" : "text-gray-900"}`}>
                        {plan.price}
                      </span>
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

                  <Link
                    href={plan.href}
                    className={`press flex items-center justify-center gap-1.5 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
                      plan.popular
                        ? "btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white shadow-md shadow-amber-400/25"
                        : "border border-gray-300 text-gray-700 hover:border-brand-gold/40 hover:text-brand-gold-deep hover:bg-amber-50"
                    }`}
                  >
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

      <div className="section-divider" />

      {/* ══ CTA FINALE ══ */}
      <section className="py-24 relative overflow-hidden bg-gradient-to-br from-amber-50 via-white to-amber-50/30">
        <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
          <div className="orb-1 absolute top-0 left-1/2 w-[500px] h-[200px] rounded-full bg-amber-300/15 blur-[80px]" />
        </div>
        <div className="relative mx-auto max-w-3xl px-4 sm:px-6 text-center">
          <ScrollReveal>
            <span className="badge-pulse eyebrow px-4 py-1.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 text-[11px] font-semibold mb-6">
              Commencez dès aujourd&apos;hui
            </span>
            <h2 className="font-display text-3xl sm:text-5xl font-extrabold text-gray-900 mb-5 leading-tight">
              Prêt à parier avec{" "}
              <span className="text-gradient-animated">l&apos;intelligence artificielle</span>
              {" "}?
            </h2>
            <p className="text-gray-600 text-lg mb-10 max-w-xl mx-auto">
              Optimisez vos mises hippiques avec une IA entraînée sur les résultats réels du PMU.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button
                size="xl"
                asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-400/25"
              >
                <Link href="/inscription">
                  Essai gratuit 7 jours — sans CB <ArrowRight className="h-5 w-5 ml-1" />
                </Link>
              </Button>
              <Button
                variant="outline"
                size="xl"
                asChild
                className="press border-gray-300 text-gray-700 hover:border-brand-gold/40 hover:bg-amber-50"
              >
                <Link href="#tarifs">Voir les tarifs</Link>
              </Button>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ══ JEU RESPONSABLE ══ */}
      <section className="py-8 border-t border-gray-100 bg-brand-warm">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <p className="text-xs text-gray-400 leading-relaxed">
            ⚠️ <strong className="text-gray-600">Jeu responsable.</strong> BlackTurf est un outil d&apos;aide à la décision,
            pas une garantie de gain. Les performances passées ne préjugent pas des performances futures.
            Interdit aux mineurs. En cas de difficulté avec le jeu :{" "}
            <a
              href="https://www.joueurs-info-service.fr"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-gray-600 transition-colors"
            >
              joueurs-info-service.fr
            </a>
            {" "}— <strong className="text-gray-600">09 74 75 13 13</strong> (gratuit, 7j/7, 8h-2h).
          </p>
        </div>
      </section>

      <Footer />
    </div>
  );
}
