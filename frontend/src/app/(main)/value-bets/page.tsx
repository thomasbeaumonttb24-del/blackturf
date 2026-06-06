"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Zap, Loader2, Lock, Star, Clock, SlidersHorizontal,
  LayoutGrid, List, TrendingUp, Filter, X, ArrowUpDown,
} from "lucide-react";
import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useValueBetsStream } from "@/hooks/useWebSocket";
import { predictionsApi } from "@/lib/api";
import { formatCote, formatEV, etoiles, formatDateTime, cn } from "@/lib/utils";

// ─── constants ───────────────────────────────────────────────
const NIVEAU_COLORS: Record<number, string> = {
  1: "text-muted-foreground", 2: "text-blue-400",
  3: "text-amber-400", 4: "text-emerald-400",
};
const NIVEAU_LABELS: Record<number, string> = {
  1: "Intéressant", 2: "Bon signal", 3: "Fort signal", 4: "Exceptionnel",
};
const NIVEAU_BORDERS: Record<number, string> = {
  1: "", 2: "border-blue-500/20", 3: "border-amber-500/30", 4: "border-emerald-500/40 ring-1 ring-emerald-500/20",
};
const DISCIPLINES = ["Tous", "Plat", "Trot", "Haies", "Steeple", "Cross"];
const SORT_OPTIONS = [
  { value: "ev_desc", label: "Espérance ↓" },
  { value: "ev_asc", label: "Espérance ↑" },
  { value: "cote_desc", label: "Cote ↓" },
  { value: "cote_asc", label: "Cote ↑" },
  { value: "heure", label: "Heure" },
  { value: "niveau", label: "Niveau" },
];

type VB = {
  vb_id: string; course_id: string; nom_cheval: string;
  hippodrome_nom: string; date_heure: string; ev_max: number;
  niveau: number;
  cote_pmu: number | null;
  cote_betfair_exchange?: number | null;
  cote_min?: number | null;
  meilleure_source: string;
  actif: boolean;
  spi_detected: boolean; spi_score: number | null;
  spi_method?: string;   // "cotes_history" | "betclic_steam" | "betfair_gap" | "market_gap"
  nb_sources?: number;
  mouvement_cote_pct?: number | null;  // % baisse depuis ouverture
  jockey_suspendu?: boolean;
  discipline?: string; confiance?: number;
};

// ─── Source badge ─────────────────────────────────────────────
const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  pmu:     { label: "PMU",     color: "text-blue-400" },
  geny:    { label: "Geny",    color: "text-purple-400" },
  bzh:     { label: "BZH",     color: "text-gray-400" },
  winamax: { label: "Winamax", color: "text-orange-400" },
  betclic: { label: "Betclic", color: "text-red-400" },
  unibet:  { label: "Unibet",  color: "text-green-400" },
  betfair: { label: "Betfair 🔵", color: "text-cyan-400" },
};

const SPI_METHOD_LABELS: Record<string, string> = {
  cotes_history: "⚡ Afflux historique",
  betclic_steam: "🔥 Afflux Betclic",
  betfair_gap:   "🎯 Écart Betfair",
  market_gap:    "📈 Écart marché",
};

// ─── sub-components ──────────────────────────────────────────
function StarRating({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <Star key={i} className={`w-3 h-3 ${i < n ? "fill-current" : "opacity-20"} ${NIVEAU_COLORS[n]}`} />
      ))}
    </span>
  );
}

function ConfidenceBar({ v }: { v: number }) {
  const pct = Math.min(v, 100);
  const color = pct >= 70 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1.5 bg-muted/60 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] font-mono" style={{ color }}>{pct.toFixed(0)}%</span>
    </div>
  );
}

function VBCard({ vb, isExpert, view }: { vb: VB; isExpert: boolean; view: "grid" | "list" }) {
  if (view === "list") {
    return (
      <Link href={`/courses/${vb.course_id}`}>
        <div className={cn(
          "flex items-center gap-4 p-3 rounded-xl border hover:bg-accent/30 transition-all group cursor-pointer",
          NIVEAU_BORDERS[vb.niveau]
        )}>
          {/* Stars */}
          <div className="shrink-0 w-16 text-center">
            <StarRating n={vb.niveau} />
            <div className={`text-[10px] mt-0.5 ${NIVEAU_COLORS[vb.niveau]}`}>
              {NIVEAU_LABELS[vb.niveau]}
            </div>
          </div>

          {/* Horse */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm truncate">{vb.nom_cheval}</span>
              {isExpert && vb.spi_detected && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-amber-400 text-amber-400 shrink-0">
                  ⚡ Afflux
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
              <span>{vb.hippodrome_nom}</span>
              {vb.discipline && <Badge variant="outline" className="text-[9px] px-1 py-0 h-3.5">{vb.discipline}</Badge>}
              <span className="flex items-center gap-0.5">
                <Clock className="w-3 h-3" />{formatDateTime(vb.date_heure)}
              </span>
            </div>
          </div>

          {/* Metrics */}
          <div className="shrink-0 flex items-center gap-5">
            {/* Meilleure cote disponible */}
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground">
                {SOURCE_LABELS[vb.meilleure_source]?.label ?? vb.meilleure_source}
              </div>
              <div className={cn(
                "font-bold text-sm font-mono tabular-nums",
                SOURCE_LABELS[vb.meilleure_source]?.color ?? "text-foreground"
              )}>
                {formatCote(vb.cote_min ?? vb.cote_pmu)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Espérance</div>
              <div className={`font-bold text-sm ${vb.ev_max > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {formatEV(vb.ev_max)}
              </div>
            </div>
            {/* Mouvement de cote */}
            {vb.mouvement_cote_pct != null && Math.abs(vb.mouvement_cote_pct) >= 5 && (
              <div className="text-right">
                <div className="text-[10px] text-muted-foreground">Mouv.</div>
                <div className={cn(
                  "font-bold text-xs font-mono tabular-nums",
                  vb.mouvement_cote_pct > 0 ? "text-emerald-400" : "text-red-400"
                )}>
                  {vb.mouvement_cote_pct > 0 ? "↓" : "↑"}{Math.abs(vb.mouvement_cote_pct).toFixed(0)}%
                </div>
              </div>
            )}
            {vb.confiance != null && (
              <div className="w-20">
                <div className="text-[10px] text-muted-foreground mb-0.5">Confiance</div>
                <ConfidenceBar v={vb.confiance} />
              </div>
            )}
          </div>
        </div>
      </Link>
    );
  }

  // grid view
  return (
    <Link href={`/courses/${vb.course_id}`}>
      <Card className={cn(
        "h-full cursor-pointer hover:border-brand-gold/40 hover:-translate-y-0.5 transition-all duration-200",
        NIVEAU_BORDERS[vb.niveau]
      )}>
        <CardContent className="p-4">
          {/* Header */}
          <div className="flex items-start justify-between mb-3">
            <div className="space-y-1">
              <StarRating n={vb.niveau} />
              {vb.nb_sources != null && vb.nb_sources > 1 && (
                <span className="text-[9px] text-muted-foreground">{vb.nb_sources} sources</span>
              )}
            </div>
            <div className="flex flex-col items-end gap-1">
              {isExpert && vb.spi_detected && vb.spi_method && (
                <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 border-amber-400 text-amber-400 gap-0.5">
                  {SPI_METHOD_LABELS[vb.spi_method] ?? "⚡ Afflux"}
                </Badge>
              )}
              {vb.jockey_suspendu && (
                <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 border-red-500 text-red-500">
                  ⚠ Jockey susp.
                </Badge>
              )}
            </div>
          </div>

          {/* Horse */}
          <div className="mb-1">
            <h3 className="font-bold text-sm truncate">{vb.nom_cheval}</h3>
            <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 flex-wrap">
              <span>{vb.hippodrome_nom}</span>
              {vb.discipline && (
                <Badge variant="outline" className="text-[9px] px-1 py-0 h-3.5">{vb.discipline}</Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
              <Clock className="w-3 h-3" />{formatDateTime(vb.date_heure)}
            </div>
          </div>

          {/* Metrics — 3 colonnes si mouvement dispo */}
          <div className={cn("grid gap-2 mt-3", vb.mouvement_cote_pct != null && Math.abs(vb.mouvement_cote_pct) >= 5 ? "grid-cols-3" : "grid-cols-2")}>
            <div className="rounded-lg bg-muted/50 p-2 text-center">
              <div className="text-[10px] text-muted-foreground">Espérance</div>
              <div className={`font-bold text-sm ${vb.ev_max > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {formatEV(vb.ev_max)}
              </div>
            </div>
            <div className="rounded-lg bg-muted/50 p-2 text-center">
              <div className={cn("text-[10px] font-medium", SOURCE_LABELS[vb.meilleure_source]?.color ?? "text-muted-foreground")}>
                {SOURCE_LABELS[vb.meilleure_source]?.label ?? "Cote"}
              </div>
              <div className={cn("font-bold text-sm font-mono tabular-nums", SOURCE_LABELS[vb.meilleure_source]?.color ?? "text-foreground")}>
                {formatCote(vb.cote_min ?? vb.cote_pmu)}
              </div>
            </div>
            {vb.mouvement_cote_pct != null && Math.abs(vb.mouvement_cote_pct) >= 5 && (
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">Mouv.</div>
                <div className={cn(
                  "font-bold text-sm font-mono tabular-nums",
                  vb.mouvement_cote_pct > 0 ? "text-emerald-400" : "text-red-400"
                )}>
                  {vb.mouvement_cote_pct > 0 ? "↓" : "↑"}{Math.abs(vb.mouvement_cote_pct).toFixed(0)}%
                </div>
              </div>
            )}
          </div>

          {/* Betfair vs PMU gap si disponible */}
          {vb.cote_betfair_exchange != null && vb.cote_pmu != null && vb.cote_pmu > vb.cote_betfair_exchange * 1.05 && (
            <div className="mt-2 flex items-center justify-between rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-2 py-1.5 text-[10px]">
              <span className="text-cyan-400 font-semibold">Betfair: {vb.cote_betfair_exchange.toFixed(1)}</span>
              <span className="text-muted-foreground">PMU: {vb.cote_pmu?.toFixed(1)}</span>
              <span className="text-cyan-400 font-bold">
                +{(((vb.cote_pmu / vb.cote_betfair_exchange) - 1) * 100).toFixed(0)}% d&apos;écart
              </span>
            </div>
          )}

          {/* Confidence */}
          {vb.confiance != null && (
            <div className="mt-2">
              <div className="text-[10px] text-muted-foreground mb-1">Confiance IA</div>
              <ConfidenceBar v={vb.confiance} />
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

// ─── main page ───────────────────────────────────────────────
export default function ValueBetsPage() {
  const { user } = useAuth();
  const [niveauMin, setNiveauMin] = useState(1);
  const [discipline, setDiscipline] = useState("Tous");
  const [sort, setSort] = useState("ev_desc");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [showFilters, setShowFilters] = useState(false);

  const isPro = user && !["free", "decouverte"].includes(user.plan ?? "free");
  const isExpert = user && ["pro", "expert"].includes(user.plan ?? "free");

  const { valueBets: streamBets, connected } = useValueBetsStream(!!isPro);

  const { data: apiBets, isLoading } = useSWR(
    isPro ? ["/value-bets", niveauMin] : null,
    () => predictionsApi.valueBets(niveauMin).then((r) => r.data),
    { refreshInterval: 60_000 }
  );

  const rawBets = (streamBets.length > 0 ? streamBets : apiBets ?? []) as VB[];

  // Filter + sort
  const bets = useMemo(() => {
    let result = [...rawBets];
    if (discipline !== "Tous") {
      result = result.filter((v) =>
        v.discipline?.toLowerCase() === discipline.toLowerCase()
      );
    }
    switch (sort) {
      case "ev_desc": result.sort((a, b) => b.ev_max - a.ev_max); break;
      case "ev_asc": result.sort((a, b) => a.ev_max - b.ev_max); break;
      case "cote_desc": result.sort((a, b) => (b.cote_pmu ?? 0) - (a.cote_pmu ?? 0)); break;
      case "cote_asc": result.sort((a, b) => (a.cote_pmu ?? 0) - (b.cote_pmu ?? 0)); break;
      case "heure": result.sort((a, b) => new Date(a.date_heure).getTime() - new Date(b.date_heure).getTime()); break;
      case "niveau": result.sort((a, b) => b.niveau - a.niveau); break;
    }
    return result;
  }, [rawBets, discipline, sort]);

  // Stats
  const nbPremium = rawBets.filter((v) => v.niveau >= 3).length;
  const avgEV = rawBets.length ? (rawBets.reduce((s, v) => s + v.ev_max, 0) / rawBets.length).toFixed(1) : null;

  // ── unauthenticated ──
  if (!user) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-20 text-center">
        <Lock className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
        <h1 className="text-2xl font-bold mb-2">Paris de valeur IA</h1>
        <p className="text-muted-foreground mb-6">
          Connectez-vous pour accéder aux paris de valeur détectés en temps réel.
        </p>
        <Button variant="brand" asChild>
          <Link href="/login?redirect=/value-bets">Se connecter</Link>
        </Button>
      </div>
    );
  }

  // ── paywall ──
  if (!isPro) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-20 text-center">
        <Zap className="h-12 w-12 mx-auto mb-4 text-brand-gold" />
        <h1 className="text-2xl font-bold mb-3">Paris de valeur en temps réel</h1>
        <p className="text-muted-foreground mb-2">
          Détection automatique espérance {">"} 0 · 4 niveaux d&apos;étoiles · Triangulation 3 sources.
        </p>
        <p className="text-muted-foreground mb-8">
          Disponible dès le plan <strong>Standard</strong> (19€/mois).
        </p>
        <div className="grid sm:grid-cols-3 gap-4 mb-8 text-left max-w-xl mx-auto">
          {["Alertes en temps réel", "Espérance > 0 garantie", "4 niveaux de confiance"].map((f) => (
            <div key={f} className="flex items-center gap-2 text-sm">
              <span className="text-emerald-400">✓</span>{f}
            </div>
          ))}
        </div>
        <Button variant="brand" size="lg" asChild>
          <Link href="/tarifs">Débloquer les paris de valeur — 19€/mois</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

      {/* ── Header ────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Zap className="h-6 w-6 text-brand-gold" />
            Paris de valeur
            {connected && (
              <span className="flex items-center gap-1 text-sm font-normal text-emerald-400 ml-2">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />En direct
              </span>
            )}
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Opportunités à espérance positive détectées par l&apos;IA
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex rounded-lg border border-border/60 overflow-hidden">
            <button
              onClick={() => setView("grid")}
              className={cn("p-1.5 transition-colors", view === "grid" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setView("list")}
              className={cn("p-1.5 transition-colors", view === "list" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
          {/* Filters toggle */}
          <Button
            variant="outline"
            size="sm"
            className={cn("gap-2", showFilters && "border-brand-gold text-brand-gold")}
            onClick={() => setShowFilters((v) => !v)}
          >
            <SlidersHorizontal className="w-4 h-4" />
            Filtres
            {(discipline !== "Tous" || niveauMin > 1) && (
              <span className="bg-brand-gold text-white rounded-full w-4 h-4 text-[10px] flex items-center justify-center">
                {(discipline !== "Tous" ? 1 : 0) + (niveauMin > 1 ? 1 : 0)}
              </span>
            )}
          </Button>
        </div>
      </div>

      {/* ── Stats bar ─────────────────────────── */}
      <div className="flex items-center gap-6 text-sm mb-4 pb-4 border-b border-border/40">
        <span className="text-muted-foreground">
          <span className="font-semibold text-foreground">{rawBets.length}</span> pari{rawBets.length !== 1 ? "s" : ""} de valeur actif{rawBets.length !== 1 ? "s" : ""}
        </span>
        {nbPremium > 0 && (
          <span className="text-amber-400 flex items-center gap-1">
            <Star className="w-3 h-3 fill-amber-400" />
            <span className="font-semibold">{nbPremium}</span> premium (★★★+)
          </span>
        )}
        {avgEV && (
          <span className="text-muted-foreground flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-emerald-400" />
            Espérance moyenne : <span className="font-semibold text-emerald-400">+{avgEV}%</span>
          </span>
        )}
      </div>

      {/* ── Filters panel ─────────────────────── */}
      {showFilters && (
        <div className="mb-6 p-4 rounded-xl border border-border/60 bg-muted/20 space-y-4">
          <div className="flex flex-wrap gap-4">
            {/* Niveau */}
            <div>
              <div className="text-xs text-muted-foreground mb-2">Niveau minimum</div>
              <div className="flex gap-1">
                {[1, 2, 3, 4].map((n) => (
                  <button
                    key={n}
                    onClick={() => setNiveauMin(n)}
                    className={cn(
                      "flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border transition-all",
                      niveauMin === n
                        ? "bg-brand-gold/20 border-brand-gold text-brand-gold font-medium"
                        : "border-border/60 text-muted-foreground hover:border-brand-gold/40 hover:text-foreground"
                    )}
                  >
                    <StarRating n={n} />
                  </button>
                ))}
              </div>
            </div>

            {/* Discipline */}
            <div>
              <div className="text-xs text-muted-foreground mb-2">Discipline</div>
              <div className="flex flex-wrap gap-1">
                {DISCIPLINES.map((d) => (
                  <button
                    key={d}
                    onClick={() => setDiscipline(d)}
                    className={cn(
                      "text-xs px-3 py-1.5 rounded-lg border transition-all",
                      discipline === d
                        ? "bg-brand-gold/20 border-brand-gold text-brand-gold font-medium"
                        : "border-border/60 text-muted-foreground hover:border-brand-gold/40 hover:text-foreground"
                    )}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* Sort */}
            <div>
              <div className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
                <ArrowUpDown className="w-3 h-3" />Trier par
              </div>
              <div className="flex flex-wrap gap-1">
                {SORT_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    onClick={() => setSort(o.value)}
                    className={cn(
                      "text-xs px-3 py-1.5 rounded-lg border transition-all",
                      sort === o.value
                        ? "bg-muted border-border text-foreground font-medium"
                        : "border-border/40 text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Active filters reset */}
          {(discipline !== "Tous" || niveauMin > 1) && (
            <button
              onClick={() => { setDiscipline("Tous"); setNiveauMin(1); }}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <X className="w-3 h-3" />Réinitialiser les filtres
            </button>
          )}
        </div>
      )}

      {/* ── Content ───────────────────────────── */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : bets.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <Zap className="h-12 w-12 mx-auto mb-4 opacity-20" />
          <p className="font-medium">Aucun pari de valeur{discipline !== "Tous" ? ` en ${discipline}` : ""} pour le moment.</p>
          <p className="text-xs mt-2">
            {discipline !== "Tous" ? "Essayez une autre discipline ou " : ""}
            Revenez lors des courses du jour.
          </p>
          {discipline !== "Tous" && (
            <button onClick={() => setDiscipline("Tous")} className="mt-3 text-xs text-brand-gold hover:underline flex items-center gap-1 mx-auto">
              <Filter className="w-3 h-3" /> Voir tous les paris de valeur
            </button>
          )}
        </div>
      ) : view === "grid" ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {bets.map((vb) => <VBCard key={vb.vb_id} vb={vb} isExpert={!!isExpert} view="grid" />)}
        </div>
      ) : (
        <div className="space-y-2">
          {bets.map((vb) => <VBCard key={vb.vb_id} vb={vb} isExpert={!!isExpert} view="list" />)}
        </div>
      )}

      {/* ── Disclaimer ────────────────────────── */}
      <div className="mt-10 p-4 rounded-xl border border-border bg-muted/30 text-xs text-muted-foreground text-center">
        ⚠️ <strong>Espérance = (Cote × Probabilité IA) − 1.</strong> Espérance positive à long terme uniquement.
        Aucune garantie de gain sur un pari individuel. Pariez de façon responsable.
      </div>
    </div>
  );
}
