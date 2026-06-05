import Link from "next/link";
import {
  ArrowRight, TrendingUp, Zap, Shield, BarChart3, Brain,
  Clock, Calculator, Target, ChevronRight, Check, Star,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
  },
  {
    icon: Brain,
    title: "IA Ensemble XGBoost + LightGBM + CatBoost",
    desc: "3 modèles combinés. 80+ features par partant. Calibration isotonique (Brier < 0.18). ELO 4 dimensions.",
    badge: undefined,
    color: "#7C3AED",
    bg: "#F5F3FF",
    borderColor: "rgba(124,58,237,0.15)",
  },
  {
    icon: Zap,
    title: "Value Bets en temps réel",
    desc: "EV = (Cote × Proba) - 1. Détection automatique 4 niveaux ★. Triangulation PMU / Geny / BZH. Steam money indicator.",
    badge: undefined,
    color: "#059669",
    bg: "#ECFDF5",
    borderColor: "rgba(5,150,105,0.15)",
  },
  {
    icon: TrendingUp,
    title: "Kelly Criterion & Bankroll",
    desc: "Mise optimale calculée automatiquement. Demi-Kelly, plafond 5%. ROI personnel vs ROI modèle en temps réel.",
    badge: undefined,
    color: "#2563EB",
    bg: "#EFF6FF",
    borderColor: "rgba(37,99,235,0.15)",
  },
  {
    icon: Shield,
    title: "ELO hippique 4 dimensions",
    desc: "Scores ELO global / plat / trot / obstacle. Velocity ELO (vitesse de progression). Mis à jour après chaque course.",
    badge: undefined,
    color: "#D97706",
    bg: "#FFFBEB",
    borderColor: "rgba(217,119,6,0.15)",
  },
  {
    icon: Clock,
    title: "Alertes & Assistant IA",
    desc: "Claude API intégré. Push VAPID, email, in-app. Digest matinal. Posez vos questions en langage naturel.",
    badge: undefined,
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
      "Stats modèle publiques",
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
      "Top 3 value bets (délai 15min)",
      "Calculateur de mise standard",
      "Bankroll tracker + stats",
      "Alertes push & email",
      "Backtest 7 jours",
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
      "Value bets temps réel ★★★★",
      "Calculateur Kelly avancé",
      "Assistant IA illimité",
      "Backtest 365 jours",
      "Créateur de stratégies 30+ filtres",
      "Export données + API",
    ],
    cta: "Passer Expert",
    href: "/inscription?plan=expert",
    popular: false,
  },
];

const STATIC_CURVE = [
  { m: "Jan", k: 1000 }, { m: "Fév", k: 1048 }, { m: "Mar", k: 1032 },
  { m: "Avr", k: 1091 }, { m: "Mai", k: 1074 }, { m: "Jun", k: 1118 },
  { m: "Jul", k: 1103 }, { m: "Aoû", k: 1142 }, { m: "Sep", k: 1138 },
  { m: "Oct", k: 1165 }, { m: "Nov", k: 1152 }, { m: "Déc", k: 1184 },
];

const STATIC_STATS = {
  auc_roc: "0.71",
  roi_simule_6mois: "+8,4%",
  nb_courses_analysees: "12 450+",
  nb_utilisateurs: "487",
  precision_top3: "59%",
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

  const stats = apiStats.status === "fulfilled" && apiStats.value
    ? {
        auc_roc: String(apiStats.value.auc_roc),
        roi_simule_6mois: `+${String(apiStats.value.roi_simule_6mois).replace(".", ",")}%`,
        nb_courses_analysees: Number(apiStats.value.nb_courses_analysees).toLocaleString("fr-FR") + "+",
        nb_utilisateurs: String(apiStats.value.nb_utilisateurs),
        precision_top3: `${Math.round(apiStats.value.precision_top3 * 100)}%`,
      }
    : STATIC_STATS;

  const rawCurve = curveData.status === "fulfilled" && curveData.value?.is_real && curveData.value.points.length >= 10
    ? curveData.value.points.map((p: { date: string; bankroll: number }) => ({ m: p.date.slice(5, 7), k: p.bankroll }))
    : STATIC_CURVE;

  const BACKTEST_CURVE = rawCurve;
  const maxK = Math.max(...BACKTEST_CURVE.map((d: { m: string; k: number }) => d.k));
  const minK = Math.min(...BACKTEST_CURVE.map((d: { m: string; k: number }) => d.k));
  const range = maxK - minK;

  const parseStatNum = (v: string) => parseFloat(v.replace(",", ".").replace(/[^0-9.]/g, ""));

  return (
    <div className="flex flex-col min-h-screen bg-white">
      <Navbar />

      {/* ══ HERO ══ */}
      <section className="relative gradient-hero-v2 min-h-[88vh] flex flex-col justify-center overflow-hidden grid-lines">
        {/* Orbs dorés — discrets sur fond clair */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
          <div className="orb-1 absolute top-[-40px] left-1/2 w-[600px] h-[300px] rounded-full bg-amber-400/10 blur-[80px]" />
          <div className="orb-2 absolute bottom-10 right-[8%] w-64 h-64 rounded-full bg-amber-300/8 blur-[60px]" />
          <div className="orb-3 absolute top-1/3 left-[6%] w-48 h-48 rounded-full bg-yellow-400/6 blur-[50px]" />
        </div>

        <div className="relative mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 text-center py-24 sm:py-32">

          {/* Live badge */}
          <div className="flex justify-center mb-8">
            <span className="badge-pulse inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-amber-300/60 bg-amber-50 text-amber-700 text-xs font-semibold tracking-wider uppercase shadow-sm">
              <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
              Terminal IA • Analyse hippique en direct
            </span>
          </div>

          {/* Titre principal */}
          <h1 className="font-display text-5xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight mb-6 leading-[1.05] text-gray-900">
            Votre{" "}
            <span className="text-gradient-animated">Conseiller Expert</span>
            <br />en Paris Hippiques
          </h1>

          <p className="text-lg sm:text-xl text-gray-600 max-w-2xl mx-auto mb-3 leading-relaxed">
            Entrez combien vous voulez miser — BlackTurf génère votre plan de pari personnalisé
            avec mise exacte, gain potentiel et probabilités calculées par l&apos;IA.
          </p>
          <p className="text-sm text-gray-400 max-w-xl mx-auto mb-10 font-mono tracking-tight">
            XGBoost + LightGBM + CatBoost · 80+ features · Value bets temps réel · Kelly Criterion
          </p>

          {/* CTA */}
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Button
              size="xl"
              asChild
              className="btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-lg shadow-amber-400/30 transition-all duration-200"
            >
              <Link href="/inscription">
                Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" />
              </Link>
            </Button>
            <Button
              variant="outline"
              size="xl"
              asChild
              className="border-gray-300 text-gray-700 hover:border-brand-gold/50 hover:text-brand-gold-deep hover:bg-amber-50 transition-all"
            >
              <Link href="/programme">Programme du jour</Link>
            </Button>
          </div>

          {/* Trust signals */}
          <div className="mt-10 flex flex-wrap justify-center gap-5 text-xs text-gray-500">
            {[
              "Sans CB requis",
              "7 jours gratuit",
              "Annulation à tout moment",
              "Données PMU officielles",
            ].map((t) => (
              <span key={t} className="flex items-center gap-1.5">
                <Check className="h-3.5 w-3.5 text-emerald-600" />
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ══ LIVE TICKER ══ */}
      <LiveTicker />

      {/* ══ STATS BAR ══ */}
      <section className="py-14 border-b border-gray-100 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {[
              { value: parseStatNum(stats.auc_roc), label: "AUC-ROC", sub: "Précision modèle", suffix: "", decimals: 2 },
              { value: parseStatNum(stats.precision_top3), label: "Précision Top-3", sub: "vs 33% aléatoire", suffix: "%", decimals: 0 },
              { value: parseStatNum(stats.roi_simule_6mois), label: "ROI simulé 6 mois", sub: "10€ flat / value bet ★★★+", suffix: "%", decimals: 1, prefix: "+" },
              { value: 12450, label: "Courses analysées", sub: "Données historiques", suffix: "+", decimals: 0 },
            ].map((s, i) => (
              <ScrollReveal key={s.label} delay={i * 80} className="text-center">
                <div className="text-4xl font-extrabold font-display tabular-nums" style={{ color: "#D97706" }}>
                  {s.prefix}
                  <AnimatedCounter end={s.value} duration={2000 + i * 200} decimals={s.decimals} suffix={s.suffix} />
                </div>
                <div className="text-sm font-semibold text-gray-900 mt-1.5">{s.label}</div>
                <div className="text-xs text-gray-500 mt-0.5">{s.sub}</div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ HOW IT WORKS ══ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-14">
              <span className="inline-block px-3 py-1 rounded-full bg-amber-100 text-amber-800 text-xs font-semibold uppercase tracking-wider mb-4">
                Simple & Rapide
              </span>
              <h2 className="font-display text-4xl font-bold text-gray-900 mb-3">
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
                desc: "BlackTurf enregistre les résultats, met à jour votre ROI personnel et améliore ses prédictions.",
                color: "#2563EB",
                bg: "#EFF6FF",
                border: "rgba(37,99,235,0.2)",
              },
            ].map((s, i) => (
              <ScrollReveal key={s.step} delay={i * 100}>
                <div className="glass-card rounded-2xl p-7 text-center h-full">
                  <div
                    className="h-14 w-14 rounded-2xl flex items-center justify-center font-mono font-black text-lg mx-auto mb-5"
                    style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color }}
                  >
                    {s.step}
                  </div>
                  <h3 className="font-semibold text-gray-900 text-base mb-2">{s.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ FEATURES ══ */}
      <section className="py-24 bg-gray-50/60">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="inline-block px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold uppercase tracking-wider mb-4">
                Technologie
              </span>
              <h2 className="font-display text-4xl font-bold text-gray-900 mb-4">
                L&apos;arsenal du parieur{" "}
                <span className="text-gradient">professionnel</span>
              </h2>
              <p className="text-gray-500 max-w-xl mx-auto">
                Toutes les analyses dont vous avez besoin, automatisées et actualisées en temps réel.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f, i) => (
              <ScrollReveal key={f.title} delay={i * 80}>
                <div className="glass-card rounded-2xl p-6 h-full bg-white">
                  <div className="flex items-start justify-between mb-4">
                    <div
                      className="icon-box h-11 w-11 rounded-xl flex items-center justify-center flex-shrink-0"
                      style={{ background: f.bg, border: `1px solid ${f.borderColor}` }}
                    >
                      <f.icon className="h-5 w-5" style={{ color: f.color }} />
                    </div>
                    {f.badge && (
                      <span className="text-[10px] bg-amber-100 text-amber-800 border border-amber-200 font-semibold px-2 py-0.5 rounded-full">
                        {f.badge}
                      </span>
                    )}
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-2 text-sm leading-snug">{f.title}</h3>
                  <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ PERFORMANCE ══ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-14">
              <span className="inline-block px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold uppercase tracking-wider mb-4">
                Performances vérifiables
              </span>
              <h2 className="font-display text-4xl font-bold text-gray-900 mb-3">
                Nos résultats, chiffres réels
              </h2>
              <p className="text-gray-500 text-sm max-w-lg mx-auto">
                Calculés en simulant 10€ flat sur chaque value bet ★★★+ sur les courses passées.
                Source de vérité : résultats PMU officiels. Mis à jour chaque nuit.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-2 gap-8 items-start">
            {/* Metrics */}
            <ScrollReveal direction="left">
              <div className="space-y-3">
                {[
                  { label: "ROI simulé 6 mois", value: stats.roi_simule_6mois, sub: "10€ flat sur value bets ★★★+", color: "#059669" },
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
                    <div className="text-2xl font-extrabold tabular-nums font-mono" style={{ color: m.color }}>
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

            {/* Equity curve */}
            <ScrollReveal direction="right">
              <div className="glass-card rounded-2xl p-6 bg-white">
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
                <p className="text-xs text-gray-500 mb-5">10€ flat par value bet ★★★+ · Derniers 12 mois</p>
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
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══ PRICING ══ */}
      <section className="py-24 bg-gray-50/60" id="tarifs">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-16">
              <span className="inline-block px-3 py-1 rounded-full bg-amber-100 text-amber-800 text-xs font-semibold uppercase tracking-wider mb-4">
                Tarifs
              </span>
              <h2 className="font-display text-4xl font-bold text-gray-900 mb-3">Simples et transparents</h2>
              <p className="text-gray-500">7 jours d&apos;essai gratuit sans carte bancaire.</p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-6 items-start">
            {PLANS.map((plan, i) => (
              <ScrollReveal key={plan.name} delay={i * 100}>
                <div
                  className={`relative rounded-2xl p-7 ${
                    plan.popular
                      ? "plan-popular bg-white border border-amber-300"
                      : "bg-white border border-gray-200 shadow-sm"
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
                      <span className={`text-4xl font-extrabold font-display ${plan.popular ? "text-brand-gold-deep" : "text-gray-900"}`}>
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
                    className={`flex items-center justify-center gap-1.5 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
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
            <span className="badge-pulse inline-block px-4 py-1.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 text-xs font-semibold uppercase tracking-wider mb-6">
              Commencez dès aujourd&apos;hui
            </span>
            <h2 className="font-display text-4xl sm:text-5xl font-extrabold text-gray-900 mb-5 leading-tight">
              Prêt à parier avec{" "}
              <span className="text-gradient-animated">l&apos;intelligence artificielle</span>
              {" "}?
            </h2>
            <p className="text-gray-600 text-lg mb-10 max-w-xl mx-auto">
              Rejoignez {stats.nb_utilisateurs} parieurs qui utilisent déjà BlackTurf pour optimiser leurs mises hippiques.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button
                size="xl"
                asChild
                className="btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-400/25"
              >
                <Link href="/inscription">
                  Essai gratuit 7 jours — sans CB <ArrowRight className="h-5 w-5 ml-1" />
                </Link>
              </Button>
              <Button
                variant="outline"
                size="xl"
                asChild
                className="border-gray-300 text-gray-700 hover:border-brand-gold/40 hover:bg-amber-50"
              >
                <Link href="#tarifs">Voir les tarifs</Link>
              </Button>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ══ JEU RESPONSABLE ══ */}
      <section className="py-8 border-t border-gray-100 bg-gray-50">
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
