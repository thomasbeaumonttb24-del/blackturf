"use client";

/**
 * Onglet « Modèle » — la trajectoire de l'algorithme, version après version.
 *
 * Un réentraînement par nuit produit une nouvelle version : la question utile
 * n'est pas « quelle est la métrique aujourd'hui » mais « va-t-elle dans le bon
 * sens, et l'écart entre entraînement et walk-forward se creuse-t-il ».
 */

import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Cpu, GitBranch, TrendingDown, TrendingUp } from "lucide-react";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import { Empty, Note, Section, StatTile, num, pct, signedPct } from "./kit";
import type { AlgoEvolutionPayload } from "./types";

interface CalibBin { lo: number; hi: number; n: number; proba_moy: number; freq_reelle: number }
interface CalibPayload {
  reliable?: boolean; verdict?: string; n_obs?: number; ece?: number;
  brier?: number; base_rate?: number; bins?: CalibBin[];
}
interface ConvergencePayload {
  par_semaine?: Array<{ semaine: string; n: number; brier: number | null; precision_top3: number | null; precision_top1: number | null }>;
  edge_histo?: Array<{ date: string; win_filtre: number | null; win_baseline: number | null; roi: number | null; edge_ok: boolean }>;
}

function delta(v: number | null | undefined, digits = 4, higherIsBetter = true) {
  if (v == null || !isFinite(v)) return <span className="text-gray-400">—</span>;
  const good = higherIsBetter ? v > 0 : v < 0;
  const Icon = v > 0 ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-0.5 ${v === 0 ? "text-gray-400" : good ? "text-emerald-600" : "text-red-600"}`}>
      <Icon className="h-3 w-3" />
      {v > 0 ? "+" : "−"}{Math.abs(v).toFixed(digits)}
    </span>
  );
}

export default function ModeleTab({
  algo, calib, converge,
}: {
  algo?: AlgoEvolutionPayload;
  calib?: CalibPayload;
  converge?: ConvergencePayload;
}) {
  if (!algo) return <Empty>Chargement de la trajectoire du modèle…</Empty>;

  const versions = algo.versions ?? [];
  const active = algo.active;
  const d = algo.delta_vs_precedente;
  const semaines = converge?.par_semaine ?? [];

  return (
    <div className="space-y-5">
      {/* Version active */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile
          label="Version active"
          value={active ? `v${active.version}` : "—"}
          sub={active?.date ? new Date(active.date).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }) : "—"}
          icon={<Cpu className="h-3.5 w-3.5 text-gray-300" />}
          footer={
            <span className="text-[10px] text-gray-400">
              {num(algo.total_versions)} versions entraînées au total
            </span>
          }
        />
        <StatTile
          label="AUC-ROC"
          value={active?.auc_roc?.toFixed(4) ?? "—"}
          sub={<>vs version précédente {delta(d?.auc_roc)}</>}
          hint="Capacité à classer un gagnant devant un perdant. 0,5 = hasard, 1 = parfait."
        />
        <StatTile
          label="AUC walk-forward"
          value={active?.walk_forward_auc?.toFixed(4) ?? "—"}
          sub={<>vs précédente {delta(d?.walk_forward_auc)}</>}
          hint="AUC mesurée sur des courses postérieures à l'entraînement — la seule qui compte vraiment."
        />
        <StatTile
          label="Brier"
          value={active?.brier?.toFixed(4) ?? "—"}
          sub={<>vs précédente {delta(d?.brier, 4, false)}</>}
          hint="Écart entre probabilité annoncée et réalité. Plus BAS = mieux calibré."
        />
        <StatTile
          label="Courses d'entraînement"
          value={num(active?.courses_train)}
          sub={`précision top-3 ${pct(active?.precision_top3)}`}
        />
      </div>

      {/* Trajectoire AUC — entraînement vs walk-forward, même unité, même axe */}
      <Section
        title="Trajectoire de l'AUC, version après version"
        desc="Les deux courbes sont dans la même unité. Un écart qui se creuse entre l'AUC d'entraînement et l'AUC walk-forward signale du surapprentissage."
        right={<span className="text-[10px] text-gray-400">{versions.length} dernières versions</span>}
      >
        {versions.length < 2 ? (
          <Empty>Moins de deux versions non synthétiques enregistrées.</Empty>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={versions} margin={{ top: 8, right: 12, left: -6, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis
                dataKey="version" tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                minTickGap={26} tickFormatter={(v) => `v${v}`}
              />
              <YAxis domain={[0.6, 0.9]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={44} tickFormatter={(v) => v.toFixed(2)} />
              <ReferenceLine y={0.5} stroke="#EF4444" strokeDasharray="3 3" label={{ value: "hasard", fontSize: 9, fill: "#EF4444" }} />
              <Tooltip
                labelFormatter={(l) => `Version ${l}`}
                content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} labelFormatter={(l) => `Version v${l}`} />}
              />
              <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
              <Line type="monotone" dataKey="auc_roc" name="AUC entraînement" stroke="#F59E0B" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="walk_forward_auc" name="AUC walk-forward" stroke="#3B82F6" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        )}
        <Note>
          Un décrochage brutal des deux courbes accompagne souvent un changement du volume
          d&apos;entraînement plutôt qu&apos;une régression du code : la colonne « courses » du tableau
          ci-dessous permet de le vérifier version par version avant de conclure.
        </Note>
      </Section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Erreur de calibration (Brier), version après version"
          desc="Plus bas = probabilités plus justes. Échelle propre : le Brier n'est pas superposé à l'AUC."
        >
          {versions.length < 2 ? (
            <Empty>Pas assez de versions.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={versions} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="version" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={26} tickFormatter={(v) => `v${v}`} />
                <YAxis domain={["dataMin - 0.01", "dataMax + 0.01"]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={48} tickFormatter={(v) => v.toFixed(3)} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} labelFormatter={(l) => `Version v${l}`} />} />
                <Line type="monotone" dataKey="brier" name="Brier" stroke="#8B5CF6" strokeWidth={2} dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Section>

        <Section
          title="Cadence de réentraînement (30 jours)"
          desc="Une journée à zéro signifie qu'aucun modèle n'a été produit cette nuit-là — le gel est visible ici avant d'être visible dans les résultats."
        >
          {(algo.cadence_30j ?? []).length === 0 ? (
            <Empty>Aucun réentraînement sur 30 jours.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={algo.cadence_30j} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis
                  dataKey="jour" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={20}
                  tickFormatter={(v: string) => v.slice(8) + "/" + v.slice(5, 7)}
                />
                <YAxis allowDecimals={false} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={32} />
                <Tooltip cursor={{ fill: "rgba(148,163,184,0.08)" }} content={<ChartTooltip valueFormatter={(v) => `${v} version${v > 1 ? "s" : ""}`} />} />
                <Bar dataKey="n" name="Versions entraînées" fill="#10B981" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Section>
      </div>

      {/* Convergence : deux graphiques, jamais un double axe */}
      {semaines.length > 1 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Section
            title="Précision, semaine par semaine"
            desc="Part des courses où le gagnant réel figurait dans les 3 (ou en 1re position) du classement prédit. Mesuré sur les courses terminées."
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={semaines} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis domain={[0, 100]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={40} tickFormatter={(v) => `${v} %`} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => pct(v)} />} />
                <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                <Line type="monotone" dataKey="precision_top3" name="Gagnant dans le top 3" stroke="#F59E0B" strokeWidth={2.5} dot={{ r: 2.5 }} connectNulls />
                <Line type="monotone" dataKey="precision_top1" name="Gagnant en tête" stroke="#EC4899" strokeWidth={2} dot={{ r: 2 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </Section>

          <Section
            title="Erreur Brier, semaine par semaine"
            desc="Plus bas = probabilités mieux calibrées. Graphique séparé : l'erreur et la précision ne se lisent pas sur la même échelle."
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={semaines} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis domain={[0, 0.4]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={44} tickFormatter={(v) => v.toFixed(2)} />
                <ReferenceLine y={0.18} stroke="#10B981" strokeDasharray="4 4" label={{ value: "cible 0,18", fontSize: 9, fill: "#10B981", position: "right" }} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} />} />
                <Line type="monotone" dataKey="brier" name="Erreur Brier" stroke="#3B82F6" strokeWidth={2.5} dot={{ r: 2.5 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </Section>
        </div>
      )}

      {/* Qualité de calibration */}
      {calib?.reliable && (
        <Section
          title="Les probabilités annoncées sont-elles justes ?"
          desc="Pour chaque tranche de probabilité annoncée, la fréquence réellement observée. Une calibration parfaite aligne les deux colonnes."
          right={
            <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
              {calib.verdict} · {num(calib.n_obs)} observations
            </span>
          }
        >
          <div className="grid grid-cols-3 gap-3">
            <StatTile label="Erreur de calibration (ECE)" value={pct((calib.ece ?? 0) * 100)} sub="écart moyen annoncé/réel" />
            <StatTile label="Brier (victoire)" value={calib.brier?.toFixed(4) ?? "—"} sub="plus bas = mieux" />
            <StatTile label="Taux de victoire moyen" value={pct((calib.base_rate ?? 0) * 100)} sub="base de comparaison" />
          </div>
          <div className="mt-4 space-y-1.5">
            {(calib.bins ?? []).filter((b) => b.n > 0).map((b, i) => {
              const ecart = (b.freq_reelle - b.proba_moy) * 100;
              return (
                <div key={i} className="flex items-center gap-3 text-[11px]">
                  <span className="w-16 shrink-0 tabular-nums text-gray-400">
                    {Math.round(b.lo * 100)}–{Math.round(b.hi * 100)} %
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-1.5">
                      <div className="h-2 rounded-full bg-blue-500" style={{ width: `${b.proba_moy * 100}%`, minWidth: 2 }} />
                      <span className="text-[10px] text-gray-400">annoncé {pct(b.proba_moy * 100, 0)}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <div className="h-2 rounded-full bg-amber-500" style={{ width: `${b.freq_reelle * 100}%`, minWidth: 2 }} />
                      <span className="text-[10px] text-gray-400">réel {pct(b.freq_reelle * 100, 0)}</span>
                    </div>
                  </div>
                  <span className={`w-16 shrink-0 text-right font-mono font-bold tabular-nums ${Math.abs(ecart) < 3 ? "text-gray-400" : ecart > 0 ? "text-emerald-600" : "text-red-600"}`}>
                    {signedPct(ecart, 0)}
                  </span>
                  <span className="w-14 shrink-0 text-right tabular-nums text-gray-300">{num(b.n)}</span>
                </div>
              );
            })}
          </div>
          <Note>
            Bleu = probabilité annoncée par le modèle, ambre = fréquence réellement observée sur les
            courses terminées. Un écart positif signifie que le modèle sous-estime cette tranche.
          </Note>
        </Section>
      )}

      {/* Tableau des versions */}
      <Section title="Historique des versions" desc="Les 60 dernières versions non synthétiques, de la plus récente à la plus ancienne.">
        <div className="-mx-4 max-h-[420px] overflow-auto px-4">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                <th className="py-2 pr-3 text-left font-semibold">Version</th>
                <th className="px-2 py-2 text-left font-semibold">Date</th>
                <th className="px-2 py-2 text-right font-semibold">AUC</th>
                <th className="px-2 py-2 text-right font-semibold">Walk-forward</th>
                <th className="px-2 py-2 text-right font-semibold">Brier</th>
                <th className="px-2 py-2 text-right font-semibold">Top-3</th>
                <th className="px-2 py-2 text-right font-semibold">Courses</th>
                <th className="py-2 pl-2 text-left font-semibold">État</th>
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((v) => (
                <tr key={v.version} className={`border-b border-gray-50 ${v.actif ? "bg-emerald-50/50" : ""}`}>
                  <td className="py-2 pr-3 font-mono font-semibold text-gray-800">v{v.version}</td>
                  <td className="px-2 py-2 text-gray-500">
                    {v.date ? new Date(v.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-gray-700">{v.auc_roc?.toFixed(4) ?? "—"}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-gray-700">{v.walk_forward_auc?.toFixed(4) ?? "—"}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-gray-700">{v.brier?.toFixed(4) ?? "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-500">{v.precision_top3 != null ? pct(v.precision_top3) : "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-500">{num(v.courses_train)}</td>
                  <td className="py-2 pl-2">
                    {v.actif ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                        <GitBranch className="h-3 w-3" /> active
                      </span>
                    ) : v.rollback ? (
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">rollback</span>
                    ) : (
                      <span className="text-[10px] text-gray-300">archivée</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          « Top-3 » vide sur les anciennes versions = la métrique n&apos;était pas encore mesurée à
          l&apos;époque, pas une précision nulle.
        </Note>
      </Section>
    </div>
  );
}

