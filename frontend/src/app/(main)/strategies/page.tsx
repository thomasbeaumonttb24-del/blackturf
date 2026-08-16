"use client";

import { useState } from "react";
import { Plus, Play, Trash2, Loader2, TrendingUp } from "lucide-react";
import useSWR from "swr";
import { toast } from "sonner";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useRequireAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Strategie {
  strategie_id: string;
  nom: string;
  filtres: Record<string, unknown>;
  indicateurs: Record<string, unknown>;
  alerte_email: boolean;
  partage_communaute: boolean;
  created_at: string;
}

interface BacktestResult {
  nb_paris: number;
  mise_totale: number;
  gain_net: number;
  roi_pct: number;
  taux_reussite: number;
  serie_max_perdante: number;
  courbe: Array<{ date: string; bankroll: number }>;
  avertissement: string;
}

const DISCIPLINES = ["Plat", "Attelé", "Monté", "Haies", "Steeple"];
const NIVEAUX = ["Group1", "Group2", "Group3", "Listed", "Conditions", "Réclamer"];

function StrategieCard({
  strat,
  onBacktest,
  onDelete,
}: {
  strat: Strategie;
  onBacktest: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <Card className="card-hover">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-start justify-between gap-2 mb-3">
          <h3 className="font-semibold">{strat.nom}</h3>
          <div className="flex gap-1">
            {strat.alerte_email && <Badge variant="warning" className="text-[10px]">📧 Alerte</Badge>}
            {strat.partage_communaute && <Badge variant="secondary" className="text-[10px]">🌍 Partagée</Badge>}
          </div>
        </div>

        {/* Filtres résumé */}
        <div className="flex flex-wrap gap-1 mb-3">
          {!!strat.filtres.discipline && (
            <Badge variant="outline" className="text-[10px]">{strat.filtres.discipline as string}</Badge>
          )}
          {!!strat.filtres.distance_min && (
            <Badge variant="outline" className="text-[10px]">≥{strat.filtres.distance_min as number}m</Badge>
          )}
          {!!strat.filtres.est_quinte && (
            <Badge variant="gold" className="text-[10px]">Quinté+</Badge>
          )}
        </div>

        {/* Indicateurs résumé */}
        <div className="text-xs text-muted-foreground mb-4 space-y-1">
          <div>Proba min : {(((strat.indicateurs?.proba_top3_min as number) ?? 0) * 100).toFixed(0)}%</div>
          <div>EV min : +{(((strat.indicateurs?.ev_min as number) ?? 0) * 100).toFixed(0)}%</div>
        </div>

        <div className="flex gap-2">
          <Button
            variant="brand"
            size="sm"
            className="flex-1"
            onClick={() => onBacktest(strat.strategie_id)}
          >
            <Play className="h-3 w-3" /> Simuler
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDelete(strat.strategie_id)}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function StrategiesPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [showForm, setShowForm] = useState(false);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [formData, setFormData] = useState({
    nom: "",
    discipline: "",
    distance_min: "",
    distance_max: "",
    est_quinte: false,
    proba_top3_min: "0.50",
    ev_min: "0.05",
    alerte_email: false,
  });

  const { data: strategies, mutate } = useSWR<Strategie[]>(
    user?.plan === "expert" ? "/strategies" : null,
    () => api.get("/strategies").then((r) => r.data)
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/strategies", {
        nom: formData.nom,
        filtres: {
          ...(formData.discipline && { discipline: formData.discipline }),
          ...(formData.distance_min && { distance_min: parseInt(formData.distance_min) }),
          ...(formData.distance_max && { distance_max: parseInt(formData.distance_max) }),
          ...(formData.est_quinte && { est_quinte: true }),
        },
        indicateurs: {
          proba_top3_min: parseFloat(formData.proba_top3_min),
          ev_min: parseFloat(formData.ev_min),
          niveau_vb_min: 1,
        },
        alerte_email: formData.alerte_email,
        partage_communaute: false,
      });
      toast.success("Stratégie créée !");
      setShowForm(false);
      mutate();
    } catch {
      toast.error("Erreur lors de la création");
    }
  }

  async function handleBacktest(id: string) {
    setBacktestLoading(true);
    setBacktest(null);
    try {
      const res = await api.post(`/strategies/${id}/backtest`, null, {
        params: { jours: 90, mise_fixe: 10 },
      });
      setBacktest(res.data);
    } catch {
      toast.error("Erreur lors de la simulation");
    } finally {
      setBacktestLoading(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.delete(`/strategies/${id}`);
      toast.success("Stratégie supprimée");
      mutate();
    } catch {
      toast.error("Erreur lors de la suppression");
    }
  }

  if (authLoading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>;

  if (!user || user.plan !== "expert") {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 sm:py-20 text-center">
        <TrendingUp className="h-14 w-14 sm:h-16 sm:w-16 mx-auto mb-4 text-muted-foreground opacity-50" />
        <h1 className="text-2xl sm:text-3xl font-bold mb-3">Créateur de stratégies</h1>
        <p className="text-muted-foreground text-sm sm:text-base mb-8">
          Filtres multi-critères, simulation sur 18 mois, alertes automatiques.
          Réservé au plan <strong className="text-brand-gold">Expert</strong>.
        </p>
        <Button variant="brand" size="lg" asChild>
          <Link href="/tarifs">Passer Expert — 19€/mois</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-6 sm:mb-8">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold">Stratégies</h1>
          <p className="text-muted-foreground text-sm mt-1">Filtres + simulation historique</p>
        </div>
        <Button variant="brand" className="flex-shrink-0" onClick={() => setShowForm(!showForm)}>
          <Plus className="h-4 w-4" /> <span className="hidden sm:inline">Nouvelle stratégie</span><span className="sm:hidden">Créer</span>
        </Button>
      </div>

      {/* Formulaire création */}
      {showForm && (
        <Card className="mb-6 border-brand-gold/30">
          <CardHeader><CardTitle className="text-base">Créer une stratégie</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1">Nom de la stratégie</label>
                <input
                  required
                  value={formData.nom}
                  onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  placeholder="Ma stratégie Quinté+ Plat"
                />
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <label className="block text-xs font-medium mb-1">Discipline</label>
                  <select
                    value={formData.discipline}
                    onChange={(e) => setFormData({ ...formData, discipline: e.target.value })}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="">Toutes</option>
                    {DISCIPLINES.map((d) => <option key={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1">Distance min (m)</label>
                  <input
                    type="number"
                    value={formData.distance_min}
                    onChange={(e) => setFormData({ ...formData, distance_min: e.target.value })}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                    placeholder="1200"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1">Distance max (m)</label>
                  <input
                    type="number"
                    value={formData.distance_max}
                    onChange={(e) => setFormData({ ...formData, distance_max: e.target.value })}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                    placeholder="2400"
                  />
                </div>
                <div className="flex flex-col justify-end">
                  <label className="flex items-center gap-2 text-sm cursor-pointer pb-2">
                    <input
                      type="checkbox"
                      checked={formData.est_quinte}
                      onChange={(e) => setFormData({ ...formData, est_quinte: e.target.checked })}
                    />
                    Quinté+ uniquement
                  </label>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium mb-1">Proba top-3 minimum</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min="0.3"
                      max="0.9"
                      step="0.05"
                      value={formData.proba_top3_min}
                      onChange={(e) => setFormData({ ...formData, proba_top3_min: e.target.value })}
                      className="flex-1"
                    />
                    <span className="text-sm font-mono w-12 text-right">{(parseFloat(formData.proba_top3_min) * 100).toFixed(0)}%</span>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1">EV minimum</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min="0.02"
                      max="0.50"
                      step="0.01"
                      value={formData.ev_min}
                      onChange={(e) => setFormData({ ...formData, ev_min: e.target.value })}
                      className="flex-1"
                    />
                    <span className="text-sm font-mono w-12 text-right">+{(parseFloat(formData.ev_min) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.alerte_email}
                  onChange={(e) => setFormData({ ...formData, alerte_email: e.target.checked })}
                />
                Recevoir une alerte email quand un signal est détecté
              </label>

              <div className="flex gap-2">
                <Button type="submit" variant="brand" size="sm">Créer la stratégie</Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowForm(false)}>Annuler</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Backtest résultat */}
      {backtestLoading && (
        <Card className="mb-6">
          <CardContent className="p-6 flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            <span className="text-muted-foreground text-sm">Simulation sur 90 jours en cours...</span>
          </CardContent>
        </Card>
      )}

      {backtest && (
        <Card className="mb-6 border-brand-gold/20">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-brand-gold" />
              Résultat de la simulation — 90 derniers jours
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {[
                { label: "Paris joués", value: backtest.nb_paris },
                { label: "Rendement", value: `${backtest.roi_pct >= 0 ? "+" : ""}${backtest.roi_pct}%`, color: backtest.roi_pct >= 0 ? "text-brand-emerald" : "text-destructive" },
                { label: "Réussite", value: `${backtest.taux_reussite}%` },
                { label: "Série perdante max", value: `${backtest.serie_max_perdante}` },
              ].map((m) => (
                <div key={m.label} className="rounded-lg bg-muted/30 p-3 text-center">
                  <div className="text-xs text-muted-foreground">{m.label}</div>
                  <div className={cn("text-xl font-bold", (m as { color?: string }).color)}>{m.value}</div>
                </div>
              ))}
            </div>

            {backtest.courbe.length > 1 && (
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={backtest.courbe}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} tickFormatter={(v) => `€${v}`} width={48} />
                  <Tooltip contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${v}€`, "Capital"]} />
                  <Line type="monotone" dataKey="bankroll" stroke={backtest.roi_pct >= 0 ? "#059669" : "#ef4444"} strokeWidth={2} dot={false} activeDot={{ r: 4, fill: backtest.roi_pct >= 0 ? "#059669" : "#ef4444", stroke: "#fff", strokeWidth: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            )}

            <p className="text-xs text-muted-foreground mt-3">⚠️ {backtest.avertissement}</p>
          </CardContent>
        </Card>
      )}

      {/* Liste stratégies */}
      {!strategies || strategies.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <TrendingUp className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p>Aucune stratégie. Créez votre première stratégie ci-dessus.</p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {strategies.map((s) => (
            <StrategieCard
              key={s.strategie_id}
              strat={s}
              onBacktest={handleBacktest}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
