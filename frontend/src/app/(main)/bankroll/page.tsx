"use client";

import { useState, useMemo, useCallback } from "react";
import Link from "next/link";
import {
  Download, TrendingUp, TrendingDown, Loader2,
  Wallet, Brain, Trophy, X,
  Search, Filter, ArrowUpDown, CheckCircle2, XCircle,
  Minus, BarChart2, Flame, Layers, ArrowDownRight,
} from "lucide-react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";
import { format, subDays, isAfter, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/useAuth";
import { bankrollApi } from "@/lib/api";
import { formatEuro, formatDateTime, cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────
interface Entry {
  entry_id: string; date: string; type_pari: string;
  course_id: string | null;
  numero_reunion: number | null;
  chevaux: string | null; mise: number; cote: number | null;
  resultat: string | null; gain_perte: number | null;
  suivi_reco_ia: boolean; notes: string | null;
}

// Code R{réunion}C{course} affiché : on privilégie le n° de réunion PUBLIC
// (numero_reunion = numExterne PMU) pour matcher pmu.fr ; fallback sur le suffixe
// du course_id (numOfficiel) si non disponible.
function rcCode(courseId: string | null | undefined, numeroReunion?: number | null): string | null {
  if (!courseId) return null;
  const suffix = courseId.match(/R\d+C(\d+)$/);
  if (numeroReunion && suffix) return `R${numeroReunion}C${suffix[1]}`;
  return courseId.match(/R\d+C\d+$/)?.[0] ?? null;
}
interface Stats {
  bankroll_initiale: number | null; mise_totale: number;
  gains_totaux: number; pertes_totales: number;
  roi_global: number; roi_ia_only: number;
  nb_paris: number; nb_gagnants: number; nb_perdants: number; taux_reussite: number;
}

type Period = "7j" | "30j" | "3m" | "tout";
type ResultFilter = "all" | "gagne" | "perd" | "attente";

function ResultBadge({ r }: { r: string | null }) {
  if (r === "gagne") return <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full"><CheckCircle2 className="w-3 h-3" />Gagné</span>;
  if (r === "perd")  return <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50 border border-red-100 px-2 py-0.5 rounded-full"><XCircle className="w-3 h-3" />Perdu</span>;
  if (r === "annule") return <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full"><Minus className="w-3 h-3" />Annulé</span>;
  return <span className="inline-flex text-xs font-medium text-blue-600 bg-blue-50 border border-blue-100 px-2 py-0.5 rounded-full">En attente</span>;
}

// ─── Main ────────────────────────────────────────────────────
export default function BankrollPage() {
  useRequireAuth();

  const [period, setPeriod] = useState<Period>("tout");
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  const [iaOnly, setIaOnly] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [sortCol, setSortCol] = useState<"date" | "mise" | "cote" | "gain">("date");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");

  const { data: entries, isLoading } = useSWR<Entry[]>(
    "/bankroll/entries",
    () => bankrollApi.entries().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  const { data: stats } = useSWR<Stats>(
    "/bankroll/stats",
    () => bankrollApi.stats().then((r) => r.data),
    { refreshInterval: 30_000 }
  );

  const analytics = useMemo(() => {
    if (!entries || !stats) return null;
    const sorted = [...entries].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    const initBal = stats.bankroll_initiale ?? 0;
    const periodDays: Record<Period, number> = { "7j": 7, "30j": 30, "3m": 90, "tout": 99999 };
    const cutoff = subDays(new Date(), periodDays[period]);
    const filtered = sorted.filter((e) => isAfter(parseISO(e.date), cutoff));

    let bal = initBal + sorted.filter((e) => !isAfter(parseISO(e.date), cutoff)).reduce((s, e) => s + (e.gain_perte ?? 0), 0);
    const periodPoints = filtered.map((e) => {
      bal += e.gain_perte ?? 0;
      return { date: format(parseISO(e.date), "dd/MM", { locale: fr }), bankroll: Math.round(bal * 100) / 100 };
    });

    let maxStreak = 0, streak = 0, worstStreak = 0, lossStreak = 0;
    for (const e of sorted) {
      if (e.resultat === "gagne") { streak++; maxStreak = Math.max(maxStreak, streak); lossStreak = 0; }
      else if (e.resultat === "perd") { lossStreak++; worstStreak = Math.max(worstStreak, lossStreak); streak = 0; }
    }

    // Série en cours (depuis le dernier pari réglé)
    let currentStreak = 0; let currentStreakType: "gagne" | "perd" | null = null;
    for (let i = sorted.length - 1; i >= 0; i--) {
      const r = sorted[i].resultat;
      if (r !== "gagne" && r !== "perd") continue;
      if (currentStreakType === null) { currentStreakType = r; currentStreak = 1; }
      else if (r === currentStreakType) currentStreak++;
      else break;
    }

    // Drawdown max (plus forte baisse depuis un pic de capital)
    let cum = initBal, peak = initBal, maxDrawdown = 0;
    for (const e of sorted) {
      cum += e.gain_perte ?? 0;
      peak = Math.max(peak, cum);
      maxDrawdown = Math.max(maxDrawdown, peak - cum);
    }

    // Performance par type de pari
    const typeMap = new Map<string, { type: string; nb: number; mise: number; net: number; wins: number; settled: number }>();
    for (const e of entries) {
      const m = typeMap.get(e.type_pari) ?? { type: e.type_pari, nb: 0, mise: 0, net: 0, wins: 0, settled: 0 };
      m.nb++; m.mise += e.mise; m.net += e.gain_perte ?? 0;
      if (e.resultat === "gagne") { m.wins++; m.settled++; }
      else if (e.resultat === "perd") m.settled++;
      typeMap.set(e.type_pari, m);
    }
    const byType = Array.from(typeMap.values())
      .map((m) => ({ ...m, roi: m.mise > 0 ? (m.net / m.mise) * 100 : 0, winRate: m.settled > 0 ? (m.wins / m.settled) * 100 : 0 }))
      .sort((a, b) => b.net - a.net);

    // IA vs misé manuellement
    const mk = () => ({ nb: 0, mise: 0, net: 0, wins: 0, settled: 0 });
    const iaAgg = mk(), manAgg = mk();
    for (const e of entries) {
      const b = e.suivi_reco_ia ? iaAgg : manAgg;
      b.nb++; b.mise += e.mise; b.net += e.gain_perte ?? 0;
      if (e.resultat === "gagne") { b.wins++; b.settled++; }
      else if (e.resultat === "perd") b.settled++;
    }
    const withRates = (a: ReturnType<typeof mk>) => ({ ...a, roi: a.mise > 0 ? (a.net / a.mise) * 100 : 0, winRate: a.settled > 0 ? (a.wins / a.settled) * 100 : 0 });

    // Répartition des résultats
    const resultCounts = { gagne: 0, perd: 0, attente: 0, annule: 0 };
    for (const e of entries) {
      if (e.resultat === "gagne") resultCounts.gagne++;
      else if (e.resultat === "perd") resultCounts.perd++;
      else if (e.resultat === "annule") resultCounts.annule++;
      else resultCounts.attente++;
    }

    return {
      periodPoints,
      currentBalance: initBal + stats.gains_totaux - stats.pertes_totales,
      maxStreak,
      worstStreak,
      currentStreak,
      currentStreakType,
      maxDrawdown,
      avgStake: stats.nb_paris > 0 ? stats.mise_totale / stats.nb_paris : 0,
      bestWin: Math.max(0, ...entries.map((e) => e.gain_perte ?? 0)),
      worstLoss: Math.min(0, ...entries.map((e) => e.gain_perte ?? 0)),
      byType,
      ia: withRates(iaAgg),
      manual: withRates(manAgg),
      resultCounts,
    };
  }, [entries, stats, period]);

  const filteredEntries = useMemo(() => {
    if (!entries) return [];
    return entries
      .filter((e) => {
        if (resultFilter === "gagne" && e.resultat !== "gagne") return false;
        if (resultFilter === "perd" && e.resultat !== "perd") return false;
        if (resultFilter === "attente" && e.resultat != null) return false;
        if (iaOnly && !e.suivi_reco_ia) return false;
        if (searchQ) {
          const q = searchQ.toLowerCase();
          return (e.chevaux ?? "").toLowerCase().includes(q) || e.type_pari.toLowerCase().includes(q);
        }
        return true;
      })
      .sort((a, b) => {
        const diff = {
          date: new Date(a.date).getTime() - new Date(b.date).getTime(),
          mise: a.mise - b.mise,
          cote: (a.cote ?? 0) - (b.cote ?? 0),
          gain: (a.gain_perte ?? 0) - (b.gain_perte ?? 0),
        }[sortCol];
        return sortDir === "desc" ? -diff : diff;
      });
  }, [entries, resultFilter, iaOnly, searchQ, sortCol, sortDir]);

  async function handleExport() {
    try {
      const res = await bankrollApi.export();
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a"); a.href = url; a.download = "blackturf_bankroll.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Erreur lors de l'exportation"); }
  }

  const toggleSort = useCallback((col: typeof sortCol) => {
    if (sortCol === col) setSortDir((d) => d === "desc" ? "asc" : "desc");
    else { setSortCol(col); setSortDir("desc"); }
  }, [sortCol]);

  if (isLoading && !entries) return <div className="flex justify-center py-32"><Loader2 className="w-8 h-8 animate-spin text-gray-200" /></div>;

  const netBalance = stats ? stats.gains_totaux - stats.pertes_totales : 0;
  const chartData = analytics?.periodPoints ?? [];
  const isPositive = chartData.length < 2 || chartData.at(-1)!.bankroll >= chartData[0]!.bankroll;
  const chartMin = chartData.length ? Math.min(...chartData.map((p) => p.bankroll)) * 0.995 : 0;
  const chartMax = chartData.length ? Math.max(...chartData.map((p) => p.bankroll)) * 1.005 : 100;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

      {/* Hero capital — bannière dégradée */}
      <div className="relative overflow-hidden rounded-3xl border border-gray-800/10 bg-gradient-to-br from-gray-900 via-gray-900 to-amber-950 text-white shadow-xl">
        <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-amber-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative p-6 sm:p-8">
          <div className="flex flex-col lg:flex-row lg:items-center gap-6">
            <div className="flex-1">
              <div className="flex items-center gap-2 text-amber-300/90 text-xs font-semibold uppercase tracking-wider">
                <Wallet className="w-4 h-4" /> Suivi du capital
              </div>
              <div className="mt-2 flex items-end gap-3 flex-wrap">
                <span className="text-4xl sm:text-5xl font-black tabular-nums leading-none">
                  {formatEuro(analytics?.currentBalance ?? (stats?.bankroll_initiale ?? 0))}
                </span>
                {stats && (
                  <span className={cn("flex items-center gap-1 text-sm font-bold pb-1",
                    netBalance >= 0 ? "text-emerald-400" : "text-red-400")}>
                    {netBalance >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    {netBalance >= 0 ? "+" : ""}{formatEuro(netBalance)}
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-white/55">
                Capital initial {formatEuro(stats?.bankroll_initiale ?? 0)} · {stats?.nb_paris ?? 0} paris · mis à jour aux rapports PMU réels
              </p>
              {stats && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className={cn("rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset",
                    stats.roi_global >= 0 ? "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30" : "bg-red-500/15 text-red-300 ring-red-400/30")}>
                    ROI global {stats.roi_global >= 0 ? "+" : ""}{stats.roi_global}%
                  </span>
                  <span className="rounded-full px-3 py-1 text-xs font-semibold bg-blue-500/15 text-blue-300 ring-1 ring-inset ring-blue-400/30">
                    ROI suivi IA {stats.roi_ia_only >= 0 ? "+" : ""}{stats.roi_ia_only}%
                  </span>
                  <span className="rounded-full px-3 py-1 text-xs font-semibold bg-white/10 text-white/80 ring-1 ring-inset ring-white/15">
                    {stats.taux_reussite}% réussite
                  </span>
                </div>
              )}
            </div>
            <div className="shrink-0">
              <Button variant="outline" size="sm" onClick={handleExport} className="bg-white/5 text-white/85 border-white/20 hover:bg-white/15 hover:text-white">
                <Download className="w-4 h-4 mr-1.5" />Exporter le CSV
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Table — suivi des résultats & gains enregistrés */}
      <Card className="border-gray-100 shadow-sm">
        {/* Filters */}
        <div className="p-4 border-b border-gray-50 space-y-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-300" />
              <input type="text" value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
                placeholder="Rechercher par cheval, type…"
                className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400/50" />
              {searchQ && <button onClick={() => setSearchQ("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"><X className="w-3 h-3" /></button>}
            </div>
            <div className="flex gap-2 flex-wrap">
              {([["all", "Tous"], ["gagne", "Gagnés"], ["perd", "Perdus"], ["attente", "En attente"]] as [ResultFilter, string][]).map(([r, label]) => (
                <button key={r} onClick={() => setResultFilter(r)}
                  className={cn("text-xs px-3 py-1.5 rounded-lg border font-medium transition-all",
                    resultFilter === r
                      ? r === "gagne" ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                        : r === "perd" ? "bg-red-50 border-red-200 text-red-700"
                        : "bg-amber-50 border-amber-200 text-amber-700"
                      : "border-gray-200 text-gray-500 hover:text-gray-700 bg-white")}>
                  {label}
                </button>
              ))}
              <button onClick={() => setIaOnly((v) => !v)}
                className={cn("text-xs px-3 py-1.5 rounded-lg border font-medium transition-all flex items-center gap-1",
                  iaOnly ? "bg-blue-50 border-blue-200 text-blue-700" : "border-gray-200 text-gray-500 bg-white hover:text-gray-700")}>
                <Brain className="w-3 h-3" />IA
              </button>
            </div>
          </div>
          {filteredEntries.length !== (entries?.length ?? 0) && (
            <p className="text-xs text-gray-400">{filteredEntries.length} sur {entries?.length ?? 0} paris</p>
          )}
        </div>

        <CardContent className="p-0">
          {filteredEntries.length === 0 ? (
            <div className="text-center py-16">
              <Filter className="w-10 h-10 text-gray-100 mx-auto mb-3" />
              <p className="text-sm text-gray-400">
                {!entries?.length ? "Aucun pari suivi pour le moment. Tes paris suivis depuis les pronostics apparaîtront ici." : "Aucun résultat pour ces filtres."}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50/70 text-xs text-gray-500">
                    {[
                      { key: "date", label: "Date" },
                      { key: null, label: "Type" },
                      { key: null, label: "Chevaux", hidden: "md" },
                      { key: "mise", label: "Mise", right: true },
                      { key: "cote", label: "Cote", right: true, hidden: "sm" },
                      { key: null, label: "Résultat", center: true },
                      { key: "gain", label: "+/−", right: true },
                      { key: null, label: "IA", center: true, hidden: "lg" },
                    ].map(({ key, label, right, center, hidden }) => (
                      <th key={label} className={cn("px-4 py-3 font-medium",
                        right ? "text-right" : center ? "text-center" : "text-left",
                        hidden === "md" ? "hidden md:table-cell" : hidden === "sm" ? "hidden sm:table-cell" : hidden === "lg" ? "hidden lg:table-cell" : ""
                      )}>
                        {key ? (
                          <button className="flex items-center gap-1 hover:text-gray-700 ml-auto" onClick={() => toggleSort(key as typeof sortCol)}>
                            {label}{sortCol === key && <ArrowUpDown className="w-3 h-3" />}
                          </button>
                        ) : label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredEntries.map((e) => (
                    <tr key={e.entry_id} className={cn(
                      "border-b border-gray-50 hover:bg-gray-50/50 transition-colors",
                      e.resultat === "gagne" && "bg-emerald-50/20",
                      e.resultat === "perd" && "bg-red-50/10",
                    )}>
                      <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">{formatDateTime(e.date)}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="text-xs font-medium text-gray-700">{e.type_pari}</div>
                        {rcCode(e.course_id, e.numero_reunion) && (
                          <Link href={`/courses/${e.course_id}`} className="mt-0.5 inline-flex items-center rounded bg-gray-900 px-1.5 py-0 text-[10px] font-bold text-white hover:bg-gray-700 transition-colors">
                            {rcCode(e.course_id, e.numero_reunion)}
                          </Link>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 hidden md:table-cell max-w-[100px] truncate">{e.chevaux || "—"}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-800">{formatEuro(e.mise)}</td>
                      <td className="px-4 py-3 text-right text-gray-500 hidden sm:table-cell font-mono text-xs">{e.cote?.toFixed(2) || "—"}</td>
                      <td className="px-4 py-3 text-center">
                        {/* Résultat réglé automatiquement (vrais rapports PMU). Tant que la
                            course n'est pas terminée / le rapport pas publié → « En attente ».
                            Plus de validation manuelle gagné/perdu. */}
                        <ResultBadge r={e.resultat} />
                      </td>
                      <td className={cn("px-4 py-3 text-right font-bold font-mono tabular-nums text-sm",
                        (e.gain_perte ?? 0) > 0 ? "text-emerald-600" : (e.gain_perte ?? 0) < 0 ? "text-red-500" : "text-gray-400")}>
                        {e.gain_perte !== null ? formatEuro(e.gain_perte) : "—"}
                      </td>
                      <td className="px-4 py-3 text-center hidden lg:table-cell">
                        {e.suivi_reco_ia && <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-50"><Brain className="w-3 h-3 text-blue-500" /></span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ══════════ ANALYSE & OUTILS (après le tableau) ══════════ */}
      {analytics && (
        <div className="space-y-5 pt-2">
          <h2 className="text-base font-bold text-gray-900 flex items-center gap-2">
            <BarChart2 className="w-4 h-4 text-amber-500" />Analyse &amp; outils
          </h2>

          {/* Évolution du capital */}
          {entries && entries.length > 1 && (
            <Card className="border-gray-100 shadow-sm">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-3">
                  <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-amber-500" />Évolution du capital
                  </CardTitle>
                  <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                    {(["7j", "30j", "3m", "tout"] as Period[]).map((p) => (
                      <button key={p} onClick={() => setPeriod(p)}
                        className={cn("px-2.5 py-1 text-xs font-medium transition-colors",
                          period === p ? "bg-amber-500 text-white" : "text-gray-500 hover:bg-gray-50")}>
                        {p === "tout" ? "Tout" : p}
                      </button>
                    ))}
                  </div>
                </div>
                {chartData.length > 1 && (
                  <div className={cn("text-xl font-bold mt-1 tabular-nums", isPositive ? "text-emerald-600" : "text-red-500")}>
                    {formatEuro(chartData.at(-1)!.bankroll)}
                    <span className="text-xs font-normal text-gray-400 ml-2">
                      {isPositive ? "▲" : "▼"} {formatEuro(Math.abs(chartData.at(-1)!.bankroll - chartData[0]!.bankroll))} sur la période
                    </span>
                  </div>
                )}
              </CardHeader>
              <CardContent className="pt-2">
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={chartData} margin={{ left: 0, right: 0, top: 4, bottom: 0 }}>
                    <defs>
                      <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0.12} />
                        <stop offset="95%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                      interval={Math.max(0, Math.floor(chartData.length / 6))} />
                    <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false}
                      domain={[chartMin, chartMax]} tickFormatter={(v) => `€${v.toFixed(0)}`} width={52} />
                    <Tooltip contentStyle={{ background: "#fff", border: "1px solid #f1f5f9", borderRadius: 12, fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,0.06)" }}
                      formatter={(v: number) => [formatEuro(v), "Capital"]} />
                    <Area type="monotone" dataKey="bankroll" stroke={isPositive ? "#10b981" : "#ef4444"} strokeWidth={2}
                      fill="url(#bg)" dot={false} activeDot={{ r: 4, fill: isPositive ? "#10b981" : "#ef4444", stroke: "#fff", strokeWidth: 2 }} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* 3 repères clés — aérés */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { icon: Flame, label: "Meilleure série", value: `${analytics.maxStreak}`, sub: "gagnés d'affilée", color: "text-orange-500" },
              { icon: Trophy, label: "Meilleur gain", value: formatEuro(analytics.bestWin), sub: "sur un pari", color: "text-emerald-600" },
              { icon: ArrowDownRight, label: "Drawdown max", value: formatEuro(analytics.maxDrawdown), sub: "plus forte baisse", color: "text-purple-500" },
            ].map(({ icon: Icon, label, value, sub, color }) => (
              <div key={label} className="rounded-2xl border border-gray-100 bg-white p-4 text-center">
                <Icon className={`w-5 h-5 ${color} mx-auto mb-2`} />
                <div className="text-lg font-black text-gray-900 tabular-nums leading-none">{value}</div>
                <div className="text-[11px] font-medium text-gray-600 mt-1">{label}</div>
                <div className="text-[10px] text-gray-400">{sub}</div>
              </div>
            ))}
          </div>

          {/* Performance par type de pari — diagramme net (visuel, épuré) */}
          {analytics.byType.length > 0 && (
            <Card className="border-gray-100 shadow-sm">
              <CardHeader className="pb-1">
                <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <Layers className="w-4 h-4 text-amber-500" />Performance par type de pari
                </CardTitle>
                <p className="text-[11px] text-gray-400">Bénéfice net réel par type — vert = profit, rouge = perte.</p>
              </CardHeader>
              <CardContent className="pt-3 space-y-4">
                {(() => {
                  const maxAbs = Math.max(1, ...analytics.byType.map((t) => Math.abs(t.net)));
                  return analytics.byType.map((t) => {
                    const pos = t.net >= 0;
                    const w = (Math.abs(t.net) / maxAbs) * 50; // % d'une demi-largeur (barre divergente)
                    return (
                      <div key={t.type}>
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-sm font-medium text-gray-700">{t.type}</span>
                          <span className={cn("text-sm font-bold tabular-nums", pos ? "text-emerald-600" : "text-red-500")}>
                            {pos ? "+" : ""}{formatEuro(t.net)}
                          </span>
                        </div>
                        <div className="relative h-2.5 rounded-full bg-gray-100">
                          <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300/70" />
                          {pos ? (
                            <div className="absolute inset-y-0 left-1/2 rounded-r-full bg-emerald-500" style={{ width: `${w}%` }} />
                          ) : (
                            <div className="absolute inset-y-0 right-1/2 rounded-l-full bg-red-400" style={{ width: `${w}%` }} />
                          )}
                        </div>
                      </div>
                    );
                  });
                })()}
              </CardContent>
            </Card>
          )}

          {/* IA vs manuel + Répartition */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Card className="border-gray-100 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <Brain className="w-4 h-4 text-blue-500" />Suivi IA vs manuel
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-1 grid grid-cols-2 gap-3">
                {([["Suivi IA", analytics.ia, "blue"], ["Manuel", analytics.manual, "gray"]] as const).map(([label, a, c]) => (
                  <div key={label} className={cn("rounded-xl p-3 border", c === "blue" ? "border-blue-100 bg-blue-50/50" : "border-gray-100 bg-gray-50/50")}>
                    <div className={cn("text-[10px] font-semibold uppercase tracking-wide", c === "blue" ? "text-blue-600" : "text-gray-500")}>{label}</div>
                    <div className={cn("mt-1 text-xl font-black tabular-nums leading-none", a.net >= 0 ? "text-emerald-600" : "text-red-500")}>
                      {a.net >= 0 ? "+" : ""}{Math.round(a.roi)}%
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">ROI · {a.nb} paris</div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-gray-100 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <BarChart2 className="w-4 h-4 text-purple-500" />Répartition des paris
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-1">
                {(() => {
                  const rc = analytics.resultCounts;
                  const total = Math.max(1, rc.gagne + rc.perd + rc.attente + rc.annule);
                  const segs = [
                    { k: "Gagnés", n: rc.gagne, cls: "bg-emerald-500", txt: "text-emerald-600" },
                    { k: "Perdus", n: rc.perd, cls: "bg-red-400", txt: "text-red-500" },
                    { k: "En attente", n: rc.attente, cls: "bg-amber-400", txt: "text-amber-600" },
                    { k: "Annulés", n: rc.annule, cls: "bg-gray-300", txt: "text-gray-500" },
                  ].filter((s) => s.n > 0);
                  return (
                    <>
                      <div className="flex h-3 w-full overflow-hidden rounded-full">
                        {segs.map((s) => <div key={s.k} className={s.cls} style={{ width: `${(s.n / total) * 100}%` }} title={`${s.k}: ${s.n}`} />)}
                      </div>
                      <div className="mt-3 space-y-1.5">
                        {segs.map((s) => (
                          <div key={s.k} className="flex items-center justify-between text-xs">
                            <span className="flex items-center gap-1.5 text-gray-500"><span className={cn("h-2 w-2 rounded-full", s.cls)} />{s.k}</span>
                            <span className={cn("font-semibold tabular-nums", s.txt)}>{s.n} · {Math.round((s.n / total) * 100)}%</span>
                          </div>
                        ))}
                      </div>
                    </>
                  );
                })()}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
