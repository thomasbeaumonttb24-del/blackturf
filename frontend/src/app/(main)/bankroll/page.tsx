"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import Link from "next/link";
import {
  Plus, Download, TrendingUp, TrendingDown, Loader2,
  Wallet, Target, Brain, Trophy, X,
  Search, Filter, ArrowUpDown, CheckCircle2, XCircle,
  Minus, BarChart2, Flame, Layers, Activity, ArrowDownRight, Coins,
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
import { bankrollApi, coursesApi } from "@/lib/api";
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

interface ProgrammeCourse {
  course_id: string;
  nom: string | null;
  hippodrome_nom: string;
  date_heure: string;
  statut: string;
}

type Period = "7j" | "30j" | "3m" | "tout";
type ResultFilter = "all" | "gagne" | "perd" | "attente";

const TYPE_PARIS = ["Simple Gagnant", "Simple Placé", "Couplé Gagnant", "Couplé Placé", "Tiercé", "Quarté+", "Quinté+", "2sur4"];

// ─── KPI Card ────────────────────────────────────────────────
function KPICard({ label, value, sub, trend, icon: Icon, color = "gold" }: {
  label: string; value: string; sub?: string;
  trend?: "up" | "down" | "neutral";
  icon: React.ElementType; color?: "gold" | "green" | "blue" | "purple";
}) {
  const cfg = {
    gold:   { bg: "bg-amber-50", ic: "text-amber-500", br: "border-amber-100 hover:border-amber-200" },
    green:  { bg: "bg-emerald-50", ic: "text-emerald-500", br: "border-emerald-100 hover:border-emerald-200" },
    blue:   { bg: "bg-blue-50", ic: "text-blue-500", br: "border-blue-100 hover:border-blue-200" },
    purple: { bg: "bg-purple-50", ic: "text-purple-500", br: "border-purple-100 hover:border-purple-200" },
  }[color];

  return (
    <Card className={`border ${cfg.br} transition-all hover:shadow-md`}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className={`p-2 rounded-xl ${cfg.bg}`}><Icon className={`w-4 h-4 ${cfg.ic}`} /></div>
          {trend && (
            <span className={cn("flex items-center text-xs font-medium",
              trend === "up" ? "text-emerald-600" : trend === "down" ? "text-red-500" : "text-gray-400"
            )}>
              {trend === "up" ? <TrendingUp className="w-3 h-3" /> : trend === "down" ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
            </span>
          )}
        </div>
        <div className="text-2xl font-bold text-gray-900 tabular-nums leading-none">{value}</div>
        <div className="text-xs text-gray-500 mt-1">{label}</div>
        {sub && <div className="text-[11px] text-gray-400 mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function ResultBadge({ r }: { r: string | null }) {
  if (r === "gagne") return <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full"><CheckCircle2 className="w-3 h-3" />Gagné</span>;
  if (r === "perd")  return <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50 border border-red-100 px-2 py-0.5 rounded-full"><XCircle className="w-3 h-3" />Perdu</span>;
  if (r === "annule") return <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full"><Minus className="w-3 h-3" />Annulé</span>;
  return <span className="inline-flex text-xs font-medium text-blue-600 bg-blue-50 border border-blue-100 px-2 py-0.5 rounded-full">En attente</span>;
}

// ─── Main ────────────────────────────────────────────────────
export default function BankrollPage() {
  useRequireAuth();

  const [showForm, setShowForm] = useState(false);
  const [period, setPeriod] = useState<Period>("tout");
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  const [iaOnly, setIaOnly] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [sortCol, setSortCol] = useState<"date" | "mise" | "cote" | "gain">("date");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [formData, setFormData] = useState({ type_pari: "Simple Gagnant", mise: "", cote: "", chevaux: "", notes: "", course_id: "" });

  const { data: entries, mutate: mutateEntries, isLoading } = useSWR<Entry[]>(
    "/bankroll/entries",
    () => bankrollApi.entries().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  const { data: stats, mutate: mutateStats } = useSWR<Stats>(
    "/bankroll/stats",
    () => bankrollApi.stats().then((r) => r.data),
    { refreshInterval: 30_000 }
  );

  // Courses du jour — pour lier un pari à une course (auto-règlement + filtre des
  // types de paris réellement proposés par le PMU). Chargé uniquement quand le form
  // est ouvert.
  const { data: programme } = useSWR<ProgrammeCourse[]>(
    showForm ? "/programme/bankroll-form" : null,
    () => coursesApi.programme().then((r) =>
      (r.data?.reunions ?? []).flatMap((rn: { courses: ProgrammeCourse[] }) => rn.courses)
    )
  );

  // Types de paris jouables pour la course liée (source de vérité = backend).
  const { data: parisDispo } = useSWR<{ paris_disponibles: string[] }>(
    formData.course_id ? `/courses/${formData.course_id}/paris-disponibles` : null,
    () => coursesApi.parisDisponibles(formData.course_id).then((r) => r.data)
  );

  // Options du <select> Type : restreintes à la course liée si choisie, sinon liste complète.
  const typeOptions = formData.course_id && parisDispo?.paris_disponibles?.length
    ? parisDispo.paris_disponibles
    : TYPE_PARIS;

  // Si le type courant n'est plus jouable après changement de course → reset sur le 1er dispo.
  useEffect(() => {
    if (formData.course_id && parisDispo?.paris_disponibles?.length &&
        !parisDispo.paris_disponibles.includes(formData.type_pari)) {
      setFormData((f) => ({ ...f, type_pari: parisDispo.paris_disponibles[0] }));
    }
  }, [parisDispo, formData.course_id, formData.type_pari]);

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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const { course_id, ...rest } = formData;
      await bankrollApi.create({
        ...rest,
        course_id: course_id || null,   // lié → auto-règlement par les vrais rapports PMU
        mise: parseFloat(formData.mise),
        cote: formData.cote ? parseFloat(formData.cote) : null,
        date: new Date().toISOString(),
      });
      toast.success("Pari enregistré !");
      setShowForm(false);
      setFormData({ type_pari: "Simple Gagnant", mise: "", cote: "", chevaux: "", notes: "", course_id: "" });
      mutateEntries(); mutateStats();
    } catch { toast.error("Erreur lors de l'enregistrement"); }
  }

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
            <div className="flex sm:flex-col gap-2 shrink-0">
              <Button size="sm" onClick={() => setShowForm((v) => !v)}
                className={cn("gap-1.5 font-semibold transition-all", showForm ? "bg-white/15 text-white hover:bg-white/25" : "bg-amber-500 hover:bg-amber-400 text-gray-900 shadow-lg shadow-amber-500/30")}>
                {showForm ? <><X className="w-4 h-4" />Annuler</> : <><Plus className="w-4 h-4" />Nouveau pari</>}
              </Button>
              <Button variant="outline" size="sm" onClick={handleExport} className="bg-white/5 text-white/85 border-white/20 hover:bg-white/15 hover:text-white">
                <Download className="w-4 h-4 mr-1.5" />Exporter
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Form */}
      {showForm && (
        <Card className="border-amber-200 bg-amber-50/40 shadow-sm">
          <CardContent className="p-5">
            <p className="text-sm font-semibold text-gray-700 mb-3">Enregistrer un pari</p>
            <form onSubmit={handleSubmit}>
              {/* Course liée (optionnel) — restreint les types de paris à ceux RÉELLEMENT
                  proposés par le PMU pour la course + active l'auto-règlement du gain. */}
              <div className="mb-3">
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Course (optionnel) — pour le règlement auto & les paris jouables
                </label>
                <select
                  value={formData.course_id}
                  onChange={(e) => setFormData({ ...formData, course_id: e.target.value })}
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
                >
                  <option value="">Aucune (pari libre)</option>
                  {(programme ?? [])
                    .filter((c) => c.statut !== "termine" && c.statut !== "annule")
                    .map((c) => (
                      <option key={c.course_id} value={c.course_id}>
                        {(c.course_id.match(/R\d+C\d+$/)?.[0] ?? c.course_id)} · {c.hippodrome_nom}
                        {c.date_heure ? ` · ${format(parseISO(c.date_heure), "HH:mm")}` : ""}
                      </option>
                    ))}
                </select>
                {formData.course_id && (
                  <p className="mt-1 text-[11px] text-amber-600">
                    Types limités aux paris proposés par le PMU pour cette course.
                  </p>
                )}
              </div>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
                {[
                  { label: "Type *", field: "type_pari", type: "select" },
                  { label: "Mise (€) *", field: "mise", type: "number", placeholder: "10.00", step: "0.01", min: "0" },
                  { label: "Cote", field: "cote", type: "number", placeholder: "3.50", step: "0.01", min: "1" },
                  { label: "Chevaux", field: "chevaux", type: "text", placeholder: "3, 7, 12" },
                ].map(({ label, field, type, ...rest }) => (
                  <div key={field}>
                    <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
                    {type === "select" ? (
                      <select
                        value={formData[field as keyof typeof formData]}
                        onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                        className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
                      >
                        {typeOptions.map((t) => <option key={t}>{t}</option>)}
                      </select>
                    ) : (
                      <input
                        type={type} {...rest}
                        value={formData[field as keyof typeof formData]}
                        onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                        required={label.includes("*")}
                        className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50"
                      />
                    )}
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <input type="text" value={formData.notes} onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Notes (optionnel)" className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/50" />
                <Button type="submit" className="bg-amber-500 hover:bg-amber-600 text-white font-semibold shrink-0">Enregistrer</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* KPIs */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KPICard label="Total misé" value={formatEuro(stats.mise_totale)}
            sub={`Mise moyenne : ${formatEuro(analytics?.avgStake ?? 0)}`} icon={Coins} color="gold" />
          <KPICard label="Rendement global" value={`${stats.roi_global >= 0 ? "+" : ""}${stats.roi_global}%`}
            sub={`Solde net : ${formatEuro(netBalance)}`} trend={stats.roi_global >= 0 ? "up" : "down"} icon={BarChart2} color={stats.roi_global >= 0 ? "green" : "gold"} />
          <KPICard label="Rendement suivi IA" value={`${stats.roi_ia_only >= 0 ? "+" : ""}${stats.roi_ia_only}%`}
            sub={`vs global : ${stats.roi_ia_only >= stats.roi_global ? "▲ meilleur" : "▼ inférieur"}`} trend={stats.roi_ia_only >= 0 ? "up" : "down"} icon={Brain} color="blue" />
          <KPICard label="Taux de réussite" value={`${stats.taux_reussite}%`}
            sub={`${stats.nb_gagnants}G · ${stats.nb_perdants}P · ${stats.nb_paris} paris`} icon={Target} color="purple" />
        </div>
      )}

      {/* Mini analytics */}
      {analytics && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {[
            {
              icon: Activity,
              label: "Série en cours",
              value: analytics.currentStreak > 0
                ? `${analytics.currentStreak} ${analytics.currentStreakType === "gagne" ? "gagné" : "perdu"}${analytics.currentStreak > 1 ? "s" : ""}`
                : "—",
              color: analytics.currentStreakType === "perd" ? "text-red-500" : "text-emerald-600",
            },
            { icon: Flame, label: "Meilleure série", value: `${analytics.maxStreak} gagnant${analytics.maxStreak > 1 ? "s" : ""}`, color: "text-orange-500" },
            { icon: Trophy, label: "Meilleur gain", value: formatEuro(analytics.bestWin), color: "text-emerald-600" },
            { icon: TrendingDown, label: "Pire série", value: `${analytics.worstStreak} perdu${analytics.worstStreak > 1 ? "s" : ""}`, color: "text-red-500" },
            { icon: ArrowDownRight, label: "Drawdown max", value: formatEuro(analytics.maxDrawdown), color: "text-purple-500" },
          ].map(({ icon: Icon, label, value, color }) => (
            <div key={label} className="flex items-center gap-3 p-3 rounded-xl border border-gray-100 bg-white hover:border-gray-200 transition-colors">
              <Icon className={`w-4 h-4 ${color} shrink-0`} />
              <div><div className="text-xs text-gray-400">{label}</div><div className="text-sm font-bold text-gray-900">{value}</div></div>
            </div>
          ))}
        </div>
      )}

      {/* Chart */}
      {entries && entries.length > 1 && (
        <Card className="border-gray-100 shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-amber-500" />Évolution du capital
              </CardTitle>
              <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                {(["7j", "30j", "3m", "tout"] as Period[]).map((p) => (
                  <button key={p} onClick={() => setPeriod(p)}
                    className={cn("px-3 py-1 text-xs font-medium transition-colors",
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

      {/* ── ANALYSE ─────────────────────────────────────────────── */}
      {analytics && analytics.byType.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Performance par type de pari */}
          <Card className="border-gray-100 shadow-sm lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <Layers className="w-4 h-4 text-amber-500" />Performance par type de pari
              </CardTitle>
              <p className="text-[11px] text-gray-400">Bénéfice net réel par famille de pari — repère ce qui rapporte.</p>
            </CardHeader>
            <CardContent className="pt-1 space-y-2.5">
              {(() => {
                const maxAbs = Math.max(1, ...analytics.byType.map((t) => Math.abs(t.net)));
                return analytics.byType.map((t) => {
                  const pct = Math.round((Math.abs(t.net) / maxAbs) * 100);
                  const pos = t.net >= 0;
                  return (
                    <div key={t.type} className="grid grid-cols-[1fr_auto] items-center gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs font-semibold text-gray-700 truncate">{t.type}</span>
                          <span className="text-[10px] text-gray-400 shrink-0">{t.nb} paris · {t.settled > 0 ? `${Math.round(t.winRate)}% réussite` : "en attente"}</span>
                        </div>
                        <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                          <div className={cn("h-full rounded-full transition-all", pos ? "bg-emerald-500" : "bg-red-400")} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                      <div className="text-right tabular-nums w-20">
                        <div className={cn("text-sm font-bold", pos ? "text-emerald-600" : "text-red-500")}>{pos ? "+" : ""}{formatEuro(t.net)}</div>
                        <div className={cn("text-[10px] font-medium", pos ? "text-emerald-500/80" : "text-red-400")}>ROI {pos ? "+" : ""}{Math.round(t.roi)}%</div>
                      </div>
                    </div>
                  );
                });
              })()}
            </CardContent>
          </Card>

          {/* IA vs Manuel + Répartition */}
          <div className="space-y-4">
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
                    <div className="mt-2 grid grid-cols-2 gap-x-2 text-[10px]">
                      <span className="text-gray-400">Net</span><span className={cn("text-right font-semibold tabular-nums", a.net >= 0 ? "text-emerald-600" : "text-red-500")}>{a.net >= 0 ? "+" : ""}{formatEuro(a.net)}</span>
                      <span className="text-gray-400">Réussite</span><span className="text-right font-semibold tabular-nums text-gray-700">{a.settled > 0 ? `${Math.round(a.winRate)}%` : "—"}</span>
                    </div>
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

      {/* Table */}
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
                {!entries?.length ? "Aucun pari. Cliquez « Nouveau pari » pour commencer." : "Aucun résultat pour ces filtres."}
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
    </div>
  );
}
