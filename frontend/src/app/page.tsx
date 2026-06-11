import Link from "next/link";
import type { CSSProperties } from "react";
import {
  ArrowRight, TrendingUp, Zap, Shield, Trophy,
  Bell, Calculator, ChevronRight, Check, Brain,
  Cpu, Sparkles, Database, AlertTriangle, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { ScrollReveal } from "@/components/ui/ScrollReveal";
import { LiveTicker } from "@/components/ui/LiveTicker";
import { CalculatorDemo } from "@/components/home/CalculatorDemo";

// Pronostics d'EXEMPLE (carte hero, taguée « Exemple »). Vrais pronostics =
// cotes PMU réelles, réservés aux abonnés.
const HERO_PICKS = [
  { rank: 1, nom: "Paladin Noir", cote: "3,4", p: 42, win: true },
  { rank: 2, nom: "Royal Flush", cote: "5,1", p: 28, win: false },
  { rank: 3, nom: "Vent d'Est", cote: "7,2", p: 19, win: false },
];
// Plan de mise COHÉRENT avec le pronostic ci-dessus (mêmes chevaux/cotes) : on
// répartit 50€ sur les 3 favoris du modèle. Gain = mise × (cote − 1) si ce cheval gagne.
const HERO_PLAN = [
  { key: "securite", label: "Sécurité", cheval: "Paladin Noir", stake: 25, cote: 3.4 },
  { key: "rendement", label: "Rendement", cheval: "Royal Flush", stake: 15, cote: 5.1 },
  { key: "coup", label: "Coup", cheval: "Vent d'Est", stake: 10, cote: 7.2 },
].map((p) => ({ ...p, gain: Math.round(p.stake * (p.cote - 1)) }));

// "Sous le capot" — bloc vedette en premier (bento asymétrique).
const FEATURE_MAIN = {
  icon: Brain,
  title: "Un modèle d'ensemble qui se réentraîne tout seul",
  desc: "Trois algorithmes (XGBoost, LightGBM, CatBoost) votent ensemble sur 80+ variables par partant. Après chaque réunion, le modèle confronte ses prédictions aux arrivées réelles et recalibre ses probabilités. Calibration isotonique, Brier < 0,18.",
  points: ["3 algorithmes combinés", "80+ variables / partant", "Réentraîné chaque nuit", "Probabilités calibrées"],
};
// Palette NEUTRE : un seul accent (or) pour toutes les icônes. Pas d'arc-en-ciel.
const ICON_GOLD = { color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.16)" };
const FEATURES = [
  { icon: Zap, title: "Paris de valeur", desc: "EV = (cote × proba) − 1, détectés sur 4 niveaux. Triangulation PMU / Geny / BZH.", ...ICON_GOLD },
  { icon: TrendingUp, title: "Critère de Kelly", desc: "Demi-Kelly plafonné à 5 % du capital. Votre rendement comparé en direct à celui du modèle.", ...ICON_GOLD },
  { icon: Shield, title: "ELO 4 dimensions", desc: "Global / plat / trot / obstacle + ELO de progression. Mis à jour après chaque course.", ...ICON_GOLD },
  { icon: Bell, title: "Alertes & assistant", desc: "Push, e-mail, in-app. Digest matinal. Questions en langage naturel sur une course.", ...ICON_GOLD },
  { icon: Database, title: "100 % données réelles", desc: "Programme et résultats PMU officiels. Aucun chiffre fabriqué : inconnu = « — ».", ...ICON_GOLD },
];

const PLANS = [
  { name: "Découverte", price: "0€", period: "/mois", desc: "Découvrez la plateforme",
    features: ["Programme du jour", "Cotes publiques", "1 prédiction/jour", "Statistiques publiques du modèle"],
    cta: "Commencer gratuitement", href: "/inscription", popular: false },
  { name: "Standard", price: "19€", period: "/mois", desc: "L'essentiel pour gagner", badge: "Populaire",
    features: ["5 prédictions/jour", "Top 3 paris de valeur (délai 15 min)", "Calculateur de mise standard", "Suivi du capital + statistiques", "Alertes push & e-mail", "Test sur historique 7 jours"],
    cta: "Essayer 7 jours gratuit", href: "/inscription?plan=standard", popular: true },
  { name: "Expert", price: "39€", period: "/mois", desc: "Pour les parieurs sérieux",
    features: ["Prédictions illimitées", "Paris de valeur en temps réel ★★★★", "Calculateur Kelly avancé", "Assistant illimité", "Test sur historique 365 jours", "Créateur de stratégies 30+ filtres", "Export des données + API"],
    cta: "Passer Expert", href: "/inscription?plan=expert", popular: false },
];

// Placeholders HONNÊTES si l'API stats est indisponible (intégrité : jamais d'invention).
const STATIC_STATS = { auc_roc: "—", roi_simule_6mois: "—", nb_courses_analysees: "—", nb_utilisateurs: "—", precision_top3: "—" };

async function fetchStats() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/public`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

// Dernier RÉSULTAT RÉEL vérifié (pronostic réglé) pour la carte hero. Données
// publiques (courses passées), réactualisées chaque nuit via /stats/track-record.
// Défensif : toute donnée absente/incohérente ⇒ null ⇒ la carte retombe sur l'exemple.
async function fetchLatestResult() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/v1/stats/track-record`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    const data = await res.json();
    const list = Array.isArray(data?.best_pronostics) ? data.best_pronostics : [];
    const p = list.find((x: Record<string, unknown>) =>
      x && typeof x.cheval_predit === "string" && typeof x.cote === "number"
      && x.cote > 1 && typeof x.date === "string" && (x.correct === true || x.correct === false)
    );
    if (!p) return null;
    const won = p.correct === true;
    return {
      date: String(p.date),
      hippodrome: typeof p.hippodrome === "string" ? p.hippodrome : "",
      cheval: String(p.cheval_predit),
      cote: Number(p.cote),
      won,
      pnl: won ? Math.round((Number(p.cote) - 1) * 10) : -10,
    };
  } catch { return null; }
}
export default async function HomePage() {
  const [v, latestResult] = await Promise.all([fetchStats(), fetchLatestResult()]);
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

  const parseStatNum = (s: string) => parseFloat(s.replace(",", ".").replace(/[^0-9.]/g, ""));
  const precisionNum = parseStatNum(stats.precision_top3);
  const aucNum = parseStatNum(stats.auc_roc);
  const roiNum = parseStatNum(stats.roi_simule_6mois);
  const coursesNum = parseStatNum(stats.nb_courses_analysees);

  const HERO_STATS = [
    { na: Number.isNaN(precisionNum), big: Number.isNaN(precisionNum) ? "—" : <AnimatedCounter end={precisionNum} duration={1800} decimals={0} suffix="%" />, label: "Précision Top-3", color: "#B45309" },
    { na: Number.isNaN(coursesNum), big: Number.isNaN(coursesNum) ? "—" : <><AnimatedCounter end={coursesNum} duration={2200} decimals={0} />+</>, label: "Courses analysées", color: "#111827" },
    { na: Number.isNaN(aucNum), big: Number.isNaN(aucNum) ? "—" : <AnimatedCounter end={aucNum} duration={1800} decimals={2} />, label: "AUC du modèle", color: "#111827" },
    { na: Number.isNaN(roiNum), big: Number.isNaN(roiNum) ? "—" : <>+<AnimatedCounter end={roiNum} duration={2200} decimals={1} suffix="%" /></>, label: "Rendement 6 mois", color: "#059669" },
  ];

  return (
    <div className="flex flex-col min-h-screen bg-brand-warm">
      <Navbar />

      {/* ══════════════ HERO — BENTO ══════════════ */}
      <section className="relative gradient-hero-v2 grid-lines overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
          <div className="orb-1 absolute top-[-60px] left-1/3 w-[600px] h-[280px] rounded-full bg-amber-400/10 blur-[90px]" />
          <div className="orb-2 absolute bottom-0 right-[4%] w-72 h-72 rounded-full bg-amber-200/10 blur-[70px]" />
        </div>

        <div className="relative mx-auto max-w-6xl w-full px-4 sm:px-6 lg:px-8 pt-28 pb-12 sm:pt-32 sm:pb-16">
          <div className="grid lg:grid-cols-12 gap-4 lg:gap-5 items-stretch">

            {/* ── Tuile titre (grande) — PAS de ScrollReveal : contenu hero critique,
                doit s'afficher même sans JS hydraté (sinon hero vide). ── */}
            <div className="lg:col-span-7">
              <div className="glass-card bento-feature rounded-[1.75rem] h-full p-7 sm:p-10 flex flex-col justify-center">
                <span className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-brand-gold-deep mb-6">
                  <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500" />
                  Pronostics · paris de valeur · PMU
                </span>

                <h1 className="font-display text-[2.5rem] sm:text-5xl lg:text-[3.5rem] font-extrabold tracking-tight leading-[1.04] text-gray-900">
                  Un algorithme qui{" "}
                  <span className="text-gradient-animated">réapprend</span>
                  <br className="hidden sm:block" /> à chaque course.
                </h1>

                <p className="mt-6 text-base sm:text-lg text-gray-600 max-w-xl leading-relaxed">
                  <span className="font-bold text-gray-900">Ne pariez plus au hasard.</span> L&apos;IA note
                  chaque cheval sur 80+ critères, la confronte aux cotes du marché et ne signale que les paris
                  où la probabilité réelle dépasse la cote. Vous misez quand les chiffres sont pour vous — et
                  le modèle apprend de chaque arrivée.
                </p>

                <div className="mt-8 flex flex-col sm:flex-row gap-3">
                  <Button size="xl" asChild
                    className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-lg shadow-amber-400/30 transition-all">
                    <Link href="/inscription">Essai gratuit 7 jours <ArrowRight className="h-5 w-5 ml-1" /></Link>
                  </Button>
                  <Button variant="outline" size="xl" asChild
                    className="press border-gray-300 text-gray-700 hover:border-brand-gold/50 hover:text-brand-gold-deep hover:bg-amber-50 transition-all">
                    <Link href="/programme">Programme du jour</Link>
                  </Button>
                </div>

                <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-xs text-gray-500">
                  {["Sans CB requis", "7 jours gratuit", "Annulation à tout moment"].map((t) => (
                    <span key={t} className="flex items-center gap-1.5">
                      <Check className="h-3.5 w-3.5 text-emerald-600" /> {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* ── Colonne droite : 2 tuiles data ── */}
            <div className="lg:col-span-5 flex flex-col gap-4 lg:gap-5">

              {/* Tuile pronostic */}
              <div className="flex-1">
                <div className="glass-card card-scan rounded-[1.75rem] h-full p-5">
                  <div className="flex items-center justify-between">
                    <span className="eyebrow text-amber-700 text-[10px] font-bold">
                      <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      Pronostic du modèle
                    </span>
                    <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 border border-gray-200 rounded-full px-2 py-0.5">Exemple</span>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-[10px] font-black uppercase tracking-wider text-white bg-brand-gold-deep rounded px-1.5 py-0.5">Deauville</span>
                    <span className="text-xs text-gray-400 font-mono">R4 · C5 · Plat 1600m</span>
                  </div>
                  <div className="mt-3 space-y-1.5">
                    {HERO_PICKS.map((h, i) => (
                      <div key={h.rank} className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${h.win ? "bg-amber-50 ring-1 ring-amber-200" : "bg-gray-50"}`}>
                        <span className={`num-display text-xs font-black w-5 ${h.win ? "text-brand-gold-deep" : "text-gray-400"}`}>#{h.rank}</span>
                        <span className="text-sm font-medium text-gray-900 flex-1 truncate">{h.nom}</span>
                        <div className="hidden md:block w-14 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                          <div className="proba-bar h-full rounded-full"
                            style={{ "--w": `${h.p}%`, "--d": `${0.5 + i * 0.15}s`, background: h.win ? "linear-gradient(90deg,#D97706,#F59E0B)" : "#9CA3AF" } as CSSProperties} />
                        </div>
                        <span className="num-display text-xs font-bold text-gray-700 w-9 text-right">{h.p}%</span>
                        <span className="text-[11px] font-mono text-gray-500 w-8 text-right">{h.cote}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
                      <Zap className="h-3 w-3" /> Pari de valeur ★★★ détecté
                    </span>
                    <span className="text-[11px] text-gray-400">EV <span className="num-display font-bold text-emerald-600">+14,2%</span></span>
                  </div>
                </div>
              </div>

              {/* Tuile plan + résultat */}
              <div className="flex-1">
                <div className="glass-card rounded-[1.75rem] h-full p-5">
                  <div className="flex items-center justify-between mb-2.5">
                    <span className="text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Plan pour une mise de</span>
                    <span className="num-display text-sm font-extrabold text-gray-900">50€</span>
                  </div>
                  <div className="space-y-1.5">
                    {HERO_PLAN.map((p) => (
                      <div key={p.key} className="flex items-center justify-between rounded-md bg-gray-50 py-1.5 pl-3 pr-3 text-xs">
                        <span className="font-semibold text-gray-700 w-[4.75rem] flex-shrink-0">{p.label}</span>
                        <span className="text-gray-500 flex-1 truncate">
                          <span className="font-mono text-gray-700">{p.stake}€</span> · cote {String(p.cote).replace(".", ",")}
                        </span>
                        <span className="num-display font-bold tabular-nums text-gray-900 whitespace-nowrap">+{p.gain}€</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-1.5 text-right text-[9px] uppercase tracking-wide text-gray-400">Gain net si le cheval gagne</p>

                  {latestResult ? (
                    <div className="mt-2.5">
                      <div className="mb-1 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wider text-gray-400">
                        <span className="live-dot inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        Dernier résultat vérifié · {latestResult.date}
                      </div>
                      <div className={`flex items-center justify-between rounded-xl border px-3 py-2.5 ${latestResult.won ? "vb-glow bg-gradient-to-r from-emerald-50 to-white border-emerald-200" : "bg-gray-50 border-gray-200"}`}>
                        <span className={`flex items-center gap-2 text-xs font-semibold truncate ${latestResult.won ? "text-emerald-700" : "text-gray-600"}`}>
                          {latestResult.won ? <Trophy className="h-3.5 w-3.5 flex-shrink-0" /> : <X className="h-3.5 w-3.5 flex-shrink-0" />}
                          <span className="truncate">{latestResult.cheval}{latestResult.hippodrome ? ` · ${latestResult.hippodrome}` : ""} — {latestResult.won ? "gagné" : "battu"}</span>
                        </span>
                        <span className={`num-display text-sm font-extrabold whitespace-nowrap ${latestResult.won ? "text-emerald-600" : "text-gray-500"}`}>
                          {latestResult.won ? "+" : ""}{latestResult.pnl}€
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2.5">
                      <div className="mb-1 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wider text-gray-400">
                        Exemple de résultat réglé
                      </div>
                      <div className="vb-glow flex items-center justify-between rounded-xl bg-gradient-to-r from-emerald-50 to-white border border-emerald-200 px-3 py-2.5">
                        <span className="flex items-center gap-2 text-xs font-semibold text-emerald-700 truncate">
                          <Trophy className="h-3.5 w-3.5 flex-shrink-0" />
                          <span className="truncate">Paladin Noir · Deauville — gagné</span>
                        </span>
                        <span className="num-display text-sm font-extrabold text-emerald-600 whitespace-nowrap">+24€</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ── Tuile bandeau de stats (pleine largeur) ── */}
            <div className="lg:col-span-12">
              <div className="glass-card rounded-[1.75rem] grid grid-cols-2 lg:grid-cols-4 divide-x divide-y lg:divide-y-0 divide-gray-100 overflow-hidden">
                {HERO_STATS.map((s) => (
                  <div key={s.label} className="px-5 py-5 sm:px-7 sm:py-6">
                    <div className="num-display text-3xl sm:text-4xl font-extrabold" style={{ color: s.na ? "#D1D5DB" : s.color }}>{s.big}</div>
                    <div className="text-[11px] uppercase tracking-wide text-gray-400 mt-1">{s.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <p className="mt-3 text-center lg:text-right text-[11px] text-gray-400">
            Cartes illustratives — pronostics réels, plan de mise et suivi des résultats réservés aux abonnés. Chiffres calculés sur courses passées et vérifiables.
          </p>
        </div>
      </section>

      {/* ══ RESULTS TAPE ══ */}
      <LiveTicker />

      {/* ══════════════ MÉTHODE — flux horizontal ══════════════ */}
      <section className="py-24 bg-white">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between mb-14 gap-3">
              <div>
                <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-2">
                  <Zap className="h-3.5 w-3.5" /> Comment ça marche
                </span>
                <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                  3 gestes pour vous,<br className="hidden sm:block" /> un cycle sans fin pour le modèle
                </h2>
              </div>
              <p className="text-gray-500 text-sm sm:max-w-[200px] sm:text-right">Moins de 10 secondes côté parieur.</p>
            </div>
          </ScrollReveal>

          <div className="grid md:grid-cols-3 gap-6">
            {[
              { step: "01", title: "Choisissez votre course", desc: "Le programme PMU du jour, déjà analysé. Un score de confiance 0-100 sur chaque course.", color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.18)" },
              { step: "02", title: "Entrez votre mise", desc: "Indiquez le montant. Le calculateur répartit votre plan : sécurité, rendement, coup.", color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.18)" },
              { step: "03", title: "Suivez — et le modèle apprend", desc: "BlackTurf enregistre les résultats réels, met à jour votre rendement, puis recalibre le modèle.", color: "#B45309", bg: "#FFFBEB", border: "rgba(180,83,9,0.18)" },
            ].map((s, i) => (
              <ScrollReveal key={s.step} delay={i * 100}>
                <div className={`relative h-full ${i < 2 ? "step-connector" : ""}`}>
                  <div className="glass-card rounded-2xl p-7 h-full">
                    <div className="icon-box h-14 w-14 rounded-2xl flex items-center justify-center font-mono font-black text-lg mb-5"
                      style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color }}>{s.step}</div>
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

      {/* ══════════════ SOUS LE CAPOT — bento asymétrique ══════════════ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="text-center mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Cpu className="h-3.5 w-3.5" /> Sous le capot
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Ce que l&apos;algorithme calcule{" "}
                <span className="text-gradient">pour vous</span>
              </h2>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 auto-rows-fr">
            {/* Tuile vedette */}
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
                <div className="glass-card rounded-3xl h-full p-6">
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

      {/* ══════════════ CALCULATEUR ══════════════ */}
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
                  <Calculator className="h-3.5 w-3.5" /> Exclusif
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

      {/* ══════════════ PERFORMANCE — track record (chiffres réels) ══════════════ */}
      <section className="py-24 bg-brand-warm">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <ScrollReveal>
            <div className="mb-12">
              <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
                <Shield className="h-3.5 w-3.5" /> Performances vérifiables
              </span>
              <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
                Nos résultats, en chiffres réels
              </h2>
              <p className="text-gray-500 text-sm mt-2 max-w-2xl">
                Simulés à 10€ fixes sur chaque pari de valeur ★★★+ des courses passées.
                Source de vérité : résultats PMU officiels, mis à jour chaque nuit.
              </p>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[
              { label: "Rendement simulé 6 mois", value: stats.roi_simule_6mois, sub: "10€ fixes sur chaque pari de valeur ★★★+", accent: true },
              { label: "Précision Top-3", value: stats.precision_top3, sub: "vs 33 % pour un choix au hasard" },
              { label: "AUC-ROC du modèle", value: stats.auc_roc, sub: "calibration isotonique · Brier < 0,18" },
              { label: "Courses analysées", value: stats.nb_courses_analysees, sub: "historique PMU officiel, vérifiable" },
            ].map((m, i) => (
              <ScrollReveal key={m.label} delay={i * 80}>
                <div className="metric-row flex items-center justify-between rounded-2xl border border-gray-200 bg-white px-6 py-5 shadow-sm h-full">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{m.label}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{m.sub}</p>
                  </div>
                  <div className="num-display text-3xl font-extrabold" style={{ color: m.accent ? "#059669" : "#111827" }}>{m.value}</div>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      <div className="section-divider" />

      {/* ══════════════ PRICING ══════════════ */}
      <section className="py-24 bg-white" id="tarifs">
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
                <div className={`relative rounded-3xl p-7 h-full ${plan.popular ? "plan-popular bg-white border border-amber-300 md:-translate-y-2" : "bg-white border border-gray-200 shadow-sm card-hover"}`}>
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

      <div className="section-divider" />

      {/* ══════════════ CTA FINALE ══════════════ */}
      <section className="py-24 relative overflow-hidden bg-gradient-to-br from-amber-50 via-white to-amber-50/30">
        <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
          <div className="orb-1 absolute top-0 left-1/2 w-[500px] h-[200px] rounded-full bg-amber-300/15 blur-[80px]" />
        </div>
        <div className="relative mx-auto max-w-3xl px-4 sm:px-6 text-center">
          <ScrollReveal>
            <span className="badge-pulse eyebrow px-4 py-1.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200 text-[11px] font-semibold mb-6">
              Commencez aujourd&apos;hui
            </span>
            <h2 className="font-display text-3xl sm:text-5xl font-extrabold text-gray-900 mb-5 leading-tight">
              Pariez avec{" "}
              <span className="text-gradient-animated">une méthode</span>
              {" "}— pas avec votre instinct.
            </h2>
            <p className="text-gray-600 text-lg mb-10 max-w-xl mx-auto">
              Un algorithme entraîné sur les résultats réels du PMU, qui se corrige après chaque course.
              Essayez-le 7 jours, sans engagement.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button size="xl" asChild
                className="press btn-shimmer bg-brand-gold hover:bg-brand-gold-deep text-white font-bold text-base shadow-xl shadow-amber-400/25">
                <Link href="/inscription">Essai gratuit 7 jours — sans CB <ArrowRight className="h-5 w-5 ml-1" /></Link>
              </Button>
              <Button variant="outline" size="xl" asChild
                className="press border-gray-300 text-gray-700 hover:border-brand-gold/40 hover:bg-amber-50">
                <Link href="#tarifs">Voir les tarifs</Link>
              </Button>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ══ JEU RESPONSABLE ══ */}
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
