"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import {
  ArrowLeft, TrendingUp, TrendingDown, Minus, Activity,
  Trophy, BarChart2, MapPin, Timer, Star,
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { axisTick, axisLine, tickLine, GRID, ChartTooltip, BRAND_GOLD } from "@/components/charts/chart-kit";
import { coursesApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatMontantDevise } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────
interface EloPoint {
  date: string;
  elo_avant: number;
  elo_apres: number;
  delta: number;
  discipline: string;
}

interface HistoriqueEntry {
  date: string;
  hippodrome: string;
  discipline: string;
  distance: number;
  terrain: string | null;
  position: number | null;
  nb_partants: number | null;
  cote: number | null;
  temps: string | null;
  gains: number | null;
  jockey: string | null;
  incident: string | null;
}

interface Performances {
  nb_courses: number;
  nb_victoires: number;
  nb_places: number;
  gains_total: number;
  gains_annee_n: number;
  gains_devise: string | null;   // ISO 4217 — devise locale de la réunion PMU
  nb_courses_annee: number;
  nb_victoires_annee: number;
  meilleur_temps_all: string | null;
  record_hippodrome_actuel: string | null;
}

interface TopHippo {
  hippodrome: string;
  nb_courses: number;
  taux_victoire: number;
}

interface TopDist {
  distance: string;
  nb_courses: number;
  taux_victoire: number;
}

interface TerrainStat {
  nb: number;
  taux_victoire: number;
}

interface ChevalData {
  cheval_id: string;
  nom: string;
  age: number | null;
  sexe: string | null;
  robe: string | null;
  pere: string | null;
  mere: string | null;
  pere_de_mere: string | null;
  mere_de_mere: string | null;
  eleveur: string | null;
  proprietaire: string | null;
  prix_vente_yearling: number | null;
  running_style: string | null;
  taux_en_tete: number | null;
  racing_post_url: string | null;
  elo_global: number;
  elo_plat: number;
  elo_trot: number;
  elo_obstacle: number;
  elo_trend: EloPoint[];
  performances: Performances | null;
  top_hippodromes: TopHippo[];
  top_distances: TopDist[];
  top_terrain: string | null;
  taux_par_terrain: Record<string, TerrainStat>;
  historique: HistoriqueEntry[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function eloColor(elo: number) {
  if (elo >= 1700) return "#F59E0B";
  if (elo >= 1550) return "#3B82F6";
  if (elo >= 1400) return "#10B981";
  return "#6B7280";
}

function eloTier(elo: number) {
  if (elo >= 1700) return "Élite";
  if (elo >= 1550) return "Confirmé";
  if (elo >= 1400) return "Correct";
  return "Débutant";
}

const RUNNING_STYLE_CONFIG: Record<string, { label: string; color: string }> = {
  mene:      { label: "Mène",       color: "bg-red-50 text-red-700 border-red-500/30" },
  suit_tete: { label: "Suit tête",  color: "bg-orange-50 text-orange-700 border-orange-500/30" },
  placier:   { label: "Placier",    color: "bg-blue-50 text-blue-700 border-blue-500/30" },
  ferme:     { label: "Ferme",      color: "bg-emerald-50 text-emerald-700 border-emerald-500/30" },
};

// EUR en dur : réservé aux montants réellement libellés en euros (prix de vente
// yearling, gains rapportés par course). Les gains de CARRIÈRE viennent du PMU dans
// la devise locale de la réunion → passer par formatMontantDevise().
function formatGains(val: number | null) {
  if (!val) return "—";
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(val);
}

function positionBadge(pos: number | null, incident: string | null) {
  if (incident) return <span className="text-xs font-bold text-amber-500">{incident.slice(0, 4)}</span>;
  if (!pos) return <span className="text-muted-foreground text-xs">—</span>;
  if (pos === 1)
    return <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-50 text-amber-700 text-xs font-bold border border-amber-500/30">1</span>;
  if (pos <= 3)
    return <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-50 text-emerald-700 text-xs font-bold border border-emerald-500/30">{pos}</span>;
  return <span className="text-muted-foreground text-xs font-mono">{pos}</span>;
}

function WinRateCell({ taux, nb }: { taux: number; nb: number }) {
  const pct = Math.round(taux * 100);
  const color = pct >= 30 ? "#10B981" : pct >= 15 ? "#F59E0B" : "#6B7280";
  return (
    <div className="text-center">
      <div className="font-bold font-mono tabular-nums text-sm" style={{ color }}>
        {pct}%
      </div>
      <div className="text-[10px] text-muted-foreground">{nb} courses</div>
    </div>
  );
}

const TABS = ["Carrière", "Conditions", "Hippodromes", "ELO", "Historique"] as const;
type Tab = (typeof TABS)[number];

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function ChevalPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("Carrière");

  const { data, error, isLoading } = useSWR(
    id ? `cheval-${id}` : null,
    () => coursesApi.cheval(id!).then((r) => r.data as ChevalData),
    { refreshInterval: 0 }
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Activity className="h-8 w-8 animate-spin text-brand-gold" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <p className="text-muted-foreground">Cheval introuvable.</p>
        <Link href="/programme">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Retour
          </Button>
        </Link>
      </div>
    );
  }

  const elo = data.elo_global;
  const runStyle = data.running_style ? RUNNING_STYLE_CONFIG[data.running_style] : null;

  // ELO trend: last point delta for trend arrow
  const lastDelta =
    data.elo_trend.length > 0 ? data.elo_trend[data.elo_trend.length - 1].delta : 0;

  const chartData = data.elo_trend.map((e) => ({
    date: e.date ? String(e.date).slice(0, 10) : "",
    elo: Math.round(e.elo_apres),
    delta: e.delta,
  }));

  return (
    <div className="max-w-5xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4 sm:space-y-6">
      {/* Back */}
      <Link href="/programme" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
        <ArrowLeft className="h-4 w-4" />
        Programme
      </Link>

      {/* ── Header card ─────────────────────────────────────────────── */}
      <Card className="bg-card/80 border-border/50">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-1">
              <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight">{data.nom}</h1>
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                {data.age && <span>{data.age} ans</span>}
                {data.sexe && <span className="capitalize">{data.sexe}</span>}
                {data.robe && <span className="capitalize">{data.robe}</span>}
                {data.proprietaire && <span>— {data.proprietaire}</span>}
              </div>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              {/* ELO badge */}
              <div className="flex flex-col items-center rounded-xl border border-border/50 bg-muted/30 px-4 py-2 min-w-[80px]">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">ELO</span>
                <span className="text-2xl font-extrabold font-mono tabular-nums" style={{ color: eloColor(elo) }}>
                  {Math.round(elo)}
                </span>
                <span className="text-[10px] font-semibold" style={{ color: eloColor(elo) }}>
                  {eloTier(elo)}
                </span>
              </div>

              {/* Running style */}
              {runStyle && (
                <Badge
                  variant="outline"
                  className={cn("text-xs font-semibold border", runStyle.color)}
                >
                  {runStyle.label}
                </Badge>
              )}

              {/* 30-day ELO trend */}
              <div className="flex flex-col items-center gap-0.5">
                <span className="text-[10px] text-muted-foreground">30j</span>
                {lastDelta > 5 ? (
                  <TrendingUp className="h-5 w-5 text-emerald-600" />
                ) : lastDelta < -5 ? (
                  <TrendingDown className="h-5 w-5 text-red-600" />
                ) : (
                  <Minus className="h-5 w-5 text-muted-foreground" />
                )}
                <span className={cn(
                  "text-[10px] font-mono font-bold",
                  lastDelta > 5 ? "text-emerald-600" : lastDelta < -5 ? "text-red-600" : "text-muted-foreground"
                )}>
                  {lastDelta > 0 ? "+" : ""}{Math.round(lastDelta)}
                </span>
              </div>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* ── Tabs ─────────────────────────────────────────────────────── */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={cn(
              "shrink-0 px-3 sm:px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors",
              activeTab === t
                ? "bg-brand-gold/15 text-brand-gold border border-brand-gold/30"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Carrière tab ─────────────────────────────────────────────── */}
      {activeTab === "Carrière" && (
        <div className="space-y-4">
          {/* Généalogie */}
          <Card className="bg-card/60 border-border/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Généalogie
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                {[
                  { label: "Père", value: data.pere },
                  { label: "Mère", value: data.mere },
                  { label: "Père de mère", value: data.pere_de_mere },
                  { label: "Mère de mère", value: data.mere_de_mere },
                  { label: "Éleveur", value: data.eleveur },
                  {
                    label: "Prix vente yearling",
                    value: data.prix_vente_yearling
                      ? formatGains(data.prix_vente_yearling)
                      : null,
                  },
                ].map(({ label, value }) => (
                  <div key={label} className="space-y-0.5">
                    <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</p>
                    <p className="font-semibold">{value || <span className="text-muted-foreground/50">—</span>}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Performance carrière */}
          {data.performances && (
            <Card className="bg-card/60 border-border/40">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Performance carrière
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {[
                    {
                      label: "Courses",
                      value: data.performances.nb_courses,
                      sub: `${data.performances.nb_courses_annee} cette année`,
                    },
                    {
                      label: "Victoires",
                      value: data.performances.nb_victoires,
                      sub: `${data.performances.nb_victoires_annee} cette année`,
                      color: "#F59E0B",
                    },
                    {
                      // Gains PMU = devise LOCALE de la réunion (ARS, HKD, TRY…),
                      // pas des euros. Sans devise connue → "—" plutôt qu'un
                      // montant dans une unité inventée.
                      label: "Gains totaux",
                      value: formatMontantDevise(
                        data.performances.gains_total,
                        data.performances.gains_devise,
                      ),
                      sub: `${formatMontantDevise(
                        data.performances.gains_annee_n,
                        data.performances.gains_devise,
                      )} en N`,
                      color: "#10B981",
                    },
                    {
                      label: "Meilleur temps",
                      value: data.performances.meilleur_temps_all || "—",
                      sub: data.performances.record_hippodrome_actuel
                        ? `Record: ${data.performances.record_hippodrome_actuel}`
                        : undefined,
                    },
                  ].map(({ label, value, sub, color }) => (
                    <div key={label} className="rounded-lg bg-muted/30 p-3 space-y-1">
                      <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</p>
                      <p className="text-xl font-bold font-mono tabular-nums" style={color ? { color } : {}}>
                        {value}
                      </p>
                      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
                    </div>
                  ))}
                </div>

                {/* Win rate summary */}
                <div className="mt-4 flex items-center gap-2 text-sm">
                  <Trophy className="h-4 w-4 text-brand-gold" />
                  <span className="font-semibold text-brand-gold font-mono">
                    {data.performances.nb_courses > 0
                      ? Math.round((data.performances.nb_victoires / data.performances.nb_courses) * 100)
                      : 0}%
                  </span>
                  <span className="text-muted-foreground">taux de victoire carrière</span>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Conditions tab ───────────────────────────────────────────── */}
      {activeTab === "Conditions" && (
        <div className="space-y-4">
          {/* Terrain */}
          <Card className="bg-card/60 border-border/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Stats par terrain
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-3">
                {["bon", "souple", "lourd"].map((t) => {
                  const s = data.taux_par_terrain[t];
                  return (
                    <div
                      key={t}
                      className={cn(
                        "rounded-lg border p-3 text-center space-y-1",
                        data.top_terrain === t
                          ? "border-brand-gold/40 bg-brand-gold/5"
                          : "border-border/30 bg-muted/20"
                      )}
                    >
                      <p className="text-xs font-semibold capitalize text-muted-foreground">{t}</p>
                      {s ? (
                        <WinRateCell taux={s.taux_victoire} nb={s.nb} />
                      ) : (
                        <p className="text-muted-foreground text-xs">—</p>
                      )}
                      {data.top_terrain === t && (
                        <Star className="h-3 w-3 text-brand-gold mx-auto" />
                      )}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Distance */}
          <Card className="bg-card/60 border-border/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Stats par distance
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-3">
                {data.top_distances.length > 0 ? (
                  data.top_distances.map((d) => (
                    <div key={d.distance} className="rounded-lg border border-border/30 bg-muted/20 p-3 text-center space-y-1">
                      <p className="text-xs font-semibold capitalize text-muted-foreground">
                        {d.distance === "courte"
                          ? "Courte (<1400m)"
                          : d.distance === "moyenne"
                          ? "Moyenne (1400-2000m)"
                          : "Longue (>2000m)"}
                      </p>
                      <WinRateCell taux={d.taux_victoire} nb={d.nb_courses} />
                    </div>
                  ))
                ) : (
                  <p className="col-span-3 text-sm text-muted-foreground text-center py-4">Pas de données</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Hippodromes tab ──────────────────────────────────────────── */}
      {activeTab === "Hippodromes" && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Top hippodromes de prédilection
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.top_hippodromes.length > 0 ? (
              <div className="space-y-3">
                {data.top_hippodromes.map((h, i) => {
                  const pct = Math.round(h.taux_victoire * 100);
                  const barColor = pct >= 30 ? "#F59E0B" : pct >= 15 ? "#3B82F6" : "#6B7280";
                  return (
                    <div key={h.hippodrome} className="flex items-center gap-4">
                      <span className="w-5 text-center text-xs font-bold text-muted-foreground">
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-semibold truncate">{h.hippodrome}</span>
                          <div className="flex items-center gap-3 text-xs shrink-0">
                            <span className="text-muted-foreground">{h.nb_courses} courses</span>
                            <span className="font-bold font-mono" style={{ color: barColor }}>
                              {pct}%
                            </span>
                          </div>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted/50 overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-700"
                            style={{ width: `${Math.min(pct * 2, 100)}%`, background: barColor }}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">Pas de données</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── ELO tab ──────────────────────────────────────────────────── */}
      {activeTab === "ELO" && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-brand-gold" />
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Évolution ELO (10 dernières courses)
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            {chartData.length > 1 ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                  <defs>
                    <linearGradient id="eloGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={BRAND_GOLD} stopOpacity={0.22} />
                      <stop offset="95%" stopColor={BRAND_GOLD} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid {...GRID} />
                  <XAxis
                    dataKey="date"
                    tick={axisTick}
                    axisLine={axisLine}
                    tickLine={tickLine}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis
                    tick={axisTick}
                    axisLine={axisLine}
                    tickLine={tickLine}
                    domain={["auto", "auto"]}
                    width={44}
                  />
                  <Tooltip
                    content={
                      <ChartTooltip
                        valueFormatter={(v, name) =>
                          name === "elo" ? `${Math.round(v)}` : `${v > 0 ? "+" : ""}${Math.round(v)}`
                        }
                        labelMap={{ elo: "ELO", delta: "Delta" }}
                      />
                    }
                    cursor={{ stroke: "#E5E7EB", strokeWidth: 1 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="elo"
                    stroke={BRAND_GOLD}
                    strokeWidth={2.5}
                    fill="url(#eloGrad)"
                    dot={{ fill: BRAND_GOLD, r: 3, strokeWidth: 0 }}
                    activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                Pas assez de données ELO.
              </p>
            )}

            {/* ELO par discipline */}
            <div className="mt-4 grid grid-cols-3 gap-3">
              {[
                { label: "Plat", value: data.elo_plat },
                { label: "Trot", value: data.elo_trot },
                { label: "Obstacle", value: data.elo_obstacle },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-lg bg-muted/30 p-2 text-center">
                  <p className="text-[10px] text-muted-foreground">{label}</p>
                  <p className="font-bold font-mono text-sm" style={{ color: eloColor(value) }}>
                    {Math.round(value)}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Historique tab ───────────────────────────────────────────── */}
      {activeTab === "Historique" && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              30 dernières courses
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {/* Mobile: liste de cartes compactes */}
            <div className="sm:hidden space-y-2 p-3">
              {data.historique.map((h, i) => (
                <div
                  key={i}
                  className={cn(
                    "rounded-lg border border-border/30 bg-muted/20 p-2.5",
                    h.position === 1 && "border-amber-500/40 bg-amber-500/5"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold truncate">{h.hippodrome || "—"}</p>
                      <p className="text-[11px] text-muted-foreground font-mono">
                        {h.date ? String(h.date).slice(0, 10) : "—"}
                        {h.distance ? ` · ${h.distance}m` : ""}
                      </p>
                    </div>
                    <div className="shrink-0">{positionBadge(h.position, h.incident)}</div>
                  </div>
                  <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span className="font-mono">Cote {h.cote ? h.cote.toFixed(1) : "—"}</span>
                    {h.gains ? (
                      <span className="font-mono text-emerald-600">{formatGains(h.gains)}</span>
                    ) : null}
                  </div>
                </div>
              ))}
              {data.historique.length === 0 && (
                <p className="py-8 text-center text-muted-foreground text-sm">
                  Aucun historique disponible.
                </p>
              )}
            </div>

            {/* Desktop: tableau complet */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border/30">
                    {/* Colonnes secondaires masquées sur mobile (Disc./Terrain/Gains/Jockey) */}
                    {([["Date", ""], ["Hippodrome", ""], ["Disc.", "hidden sm:table-cell"],
                       ["Dist.", ""], ["Terrain", "hidden md:table-cell"], ["Pos.", ""],
                       ["Cote", ""], ["Gains", "hidden sm:table-cell"], ["Jockey", "hidden lg:table-cell"]] as const).map(([h, cls]) => (
                      <th
                        key={h}
                        className={cn("px-3 py-2 text-left text-muted-foreground font-medium whitespace-nowrap", cls)}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.historique.map((h, i) => (
                    <tr
                      key={i}
                      className={cn(
                        "border-b border-border/20 transition-colors hover:bg-muted/20",
                        h.position === 1 && "bg-amber-500/5"
                      )}
                    >
                      <td className="px-3 py-2 font-mono whitespace-nowrap">
                        {h.date ? String(h.date).slice(0, 10) : "—"}
                      </td>
                      <td className="px-3 py-2 max-w-[120px] truncate">{h.hippodrome || "—"}</td>
                      <td className="px-3 py-2 whitespace-nowrap hidden sm:table-cell">{h.discipline || "—"}</td>
                      <td className="px-3 py-2 font-mono whitespace-nowrap">
                        {h.distance ? `${h.distance}m` : "—"}
                      </td>
                      <td className="px-3 py-2 capitalize whitespace-nowrap hidden md:table-cell">
                        {h.terrain || "—"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {positionBadge(h.position, h.incident)}
                      </td>
                      <td className="px-3 py-2 font-mono whitespace-nowrap">
                        {h.cote ? `${h.cote.toFixed(1)}` : "—"}
                      </td>
                      <td className="px-3 py-2 font-mono whitespace-nowrap text-emerald-600 hidden sm:table-cell">
                        {h.gains ? formatGains(h.gains) : "—"}
                      </td>
                      <td className="px-3 py-2 max-w-[100px] truncate text-muted-foreground hidden lg:table-cell">
                        {h.jockey || "—"}
                      </td>
                    </tr>
                  ))}
                  {data.historique.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                        Aucun historique disponible.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
