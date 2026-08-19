"use client";

/**
 * Onglet « Apprentissage » — ce que le système corrige tout seul, et sur quoi.
 *
 * Température de calibration, détecteur de dérive, poids de features, poids
 * appris par profil, ROI par signal, biais contextuels, journal course par
 * course. Tout provient d'états réellement persistés : un module qui n'a pas
 * encore assez de données affiche « en attente », jamais une valeur neutre
 * déguisée en mesure.
 */

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Thermometer, Zap } from "lucide-react";
import { format } from "date-fns";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import {
  DIVERGING_NEG, DIVERGING_POS, Empty, Note, Section, StatTile,
  num, pct, signedPct, tone,
} from "./kit";

interface Feature { name: string; weight: number }
interface HistoryEntry {
  log_id: string; hippodrome?: string; discipline?: string;
  brier_score?: number; was_surprise?: boolean;
  gagnant_proba_ia?: number; gagnant_rang_predit?: number;
  temperature_update?: number; analyzed_at: string;
}
interface BiasRow {
  contexte: string; discipline?: string; terrain?: string; hippodrome?: string;
  nb_courses: number; taux_surprise: number; brier_moyen?: number;
  correction_factor: number; favori_win_rate?: number;
}

const SEVERITY: Record<string, { label: string; cls: string; aide: string }> = {
  critical: {
    label: "Dérive critique",
    cls: "border-red-200 bg-red-50 text-red-700",
    aide: "ADWIN et/ou Page-Hinkley ont détecté une rupture nette de la qualité des probabilités.",
  },
  warning: {
    label: "Avertissement",
    cls: "border-amber-200 bg-amber-50 text-amber-700",
    aide: "Signal de dérive naissant — à surveiller, pas encore une rupture.",
  },
  none: {
    label: "Stable",
    cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
    aide: "Aucune rupture détectée sur la fenêtre glissante.",
  },
};

function TemperatureGauge({ temp }: { temp?: number | null }) {
  const t = typeof temp === "number" && isFinite(temp) ? temp : 1.0;
  const pctPos = Math.min(Math.max(((t - 0.5) / 1.5) * 100, 0), 100);
  const color = t < 0.85 ? "#3B82F6" : t > 1.2 ? "#EF4444" : "#10B981";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[10px] text-gray-400">
        <span>0,5 — probas plus tranchées</span>
        <span className="font-mono text-sm font-bold" style={{ color }}>{t.toFixed(4)}</span>
        <span>2,0 — probas plus prudentes</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-gray-100">
        <div className="absolute inset-y-0 left-1/3 w-px bg-gray-300" />
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pctPos}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

export default function ApprentissageTab({
  alState, mlStatus, learning, history, biasMatrix, histLimit, setHistLimit, loadingHistory,
}: {
  alState?: Record<string, any>;
  mlStatus?: Record<string, any>;
  learning?: Record<string, any>;
  history?: HistoryEntry[];
  biasMatrix?: BiasRow[];
  histLimit: number;
  setHistLimit: (n: number) => void;
  loadingHistory: boolean;
}) {
  const [showBiasAll, setShowBiasAll] = useState(false);

  const al = alState?.adaptive_learning ?? mlStatus?.adaptive_learning ?? {};
  const dd = alState?.drift_detector ?? mlStatus?.drift_detector ?? {};
  const topFeatures: Feature[] = al.top_features ?? [];
  const sev = SEVERITY[dd.severity ?? "none"] ?? SEVERITY.none;
  const calibration = alState?.calibration;

  const histPoints = (history ?? []).slice().reverse().map((h) => ({
    date: h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "",
    brier: h.brier_score ?? null,
    surprise: !!h.was_surprise,
  }));

  const biasRows = (biasMatrix ?? []).slice(0, showBiasAll ? 100 : 12);

  return (
    <div className="space-y-5">
      {/* État du moteur */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className={`rounded-xl border p-4 ${sev.cls}`} title={sev.aide}>
          <div className="flex items-center gap-2">
            {dd.severity === "none" || !dd.severity ? (
              <CheckCircle2 className="h-5 w-5" />
            ) : (
              <AlertTriangle className="h-5 w-5" />
            )}
            <div>
              <div className="text-sm font-bold">{sev.label}</div>
              <div className="text-[11px] opacity-80">Détecteur de dérive ADWIN + Page-Hinkley</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-90">
            <span>Brier moyen {dd.brier_mean?.toFixed(4) ?? "—"}</span>
            <span>Surprises {dd.surprise_rate != null ? pct(dd.surprise_rate * 100) : "—"}</span>
            {dd.adwin_triggered && <span className="font-semibold">ADWIN déclenché</span>}
            {dd.ph_triggered && <span className="font-semibold">Page-Hinkley déclenché</span>}
          </div>
        </div>

        <div className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-amber-500" />
            <span className="text-sm font-bold text-gray-900">Température de calibration</span>
          </div>
          <TemperatureGauge temp={al.temperature ?? 1.0} />
          <div className="mt-2 flex justify-between text-[11px] text-gray-400">
            <span>{num(al.n_races)} courses analysées</span>
            <span>Brier EMA {al.brier_ema?.toFixed(3) ?? "—"}</span>
          </div>
        </div>

        <div className="rounded-xl border border-gray-100 bg-white p-4 shadow-sm">
          <div className="mb-3 text-sm font-bold text-gray-900">Corrections appliquées à l&apos;inférence</div>
          {!calibration ? (
            <p className="text-[11px] text-gray-400">État de calibration indisponible.</p>
          ) : (
            <div className="space-y-2 text-[11px]">
              {[
                { k: "Calibration isotonique", actif: calibration.isotonique?.actif, detail: `${num(calibration.isotonique?.n_points)} points · ${num(calibration.isotonique?.n_obs)} obs` },
                { k: "Calibration longshots", actif: calibration.longshots?.actif, detail: `${num(calibration.longshots?.n_obs)} obs` },
                { k: "Tilt des poids de features", actif: calibration.feature_weight_tilt?.actif, detail: `${num(calibration.feature_weight_tilt?.courses_apprises)} / ${num(calibration.feature_weight_tilt?.courses_requises)} courses` },
              ].map((c) => (
                <div key={c.k} className="flex items-center justify-between gap-2">
                  <span className="truncate text-gray-600">{c.k}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-[10px] text-gray-400">{c.detail}</span>
                    <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${c.actif ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 bg-gray-50 text-gray-500"}`}>
                      {c.actif ? "active" : "en attente"}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Edge hors-échantillon */}
      {learning?.edge && (
        <Section
          title="Le filtre de conviction bat-il le marché ?"
          desc="Mesuré sur des courses jamais vues à l'entraînement : taux de réussite des paris à forte conviction contre le taux obtenu en jouant tout."
          right={
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${learning.edge.edge_ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : learning.edge.enough_filt === false ? "border-amber-200 bg-amber-50 text-amber-700" : "border-red-200 bg-red-50 text-red-700"}`}>
              {learning.edge.edge_ok ? "avantage confirmé" : learning.edge.enough_filt === false ? "échantillon insuffisant" : "avantage à surveiller"}
            </span>
          }
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Réussite filtrée" value={pct((learning.edge.win_filtre ?? 0) * 100)} sub={`${num(learning.edge.n_filt)} paris retenus`} valueClass="text-emerald-600" />
            <StatTile label="Réussite sans filtre" value={pct((learning.edge.win_baseline ?? 0) * 100)} sub="en jouant tout" />
            <StatTile label="ROI plafonné" value={signedPct(learning.edge.roi_plafonne)} valueClass={tone(learning.edge.roi_plafonne)} sub="gains extrêmes bornés" />
            <StatTile label="Courses de test" value={num(learning.edge.n_test)} sub={learning.edge.mesure_le ? `mesuré le ${new Date(learning.edge.mesure_le).toLocaleDateString("fr-FR")}` : "—"} />
          </div>
          {learning.edge.enough_filt === false && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] text-amber-800">
              <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
              <span>
                Échantillon filtré trop petit ({num(learning.edge.n_filt)} paris) : ces chiffres sont
                dominés par la variance, pas par un avantage établi.
              </span>
            </div>
          )}
        </Section>
      )}

      {/* Poids appris par profil */}
      {learning?.profil_weights?.profils && (
        <Section
          title="Poids appris par profil"
          desc="Multiplicateur appliqué à chaque type de pari selon ce que le profil a réellement encaissé. En dessous de 10 conseils réglés, le poids reste neutre — jamais inventé."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(["conservateur", "equilibre", "agressif"] as const).map((pk) => {
              const p = learning.profil_weights.profils[pk];
              if (!p) return null;
              const labels: Record<string, string> = { conservateur: "Prudent", equilibre: "Modéré", agressif: "Risqué" };
              return (
                <div key={pk} className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-gray-900">{labels[pk]}</span>
                    <span className="text-[10px] text-gray-400">{num(p.n_runs)} conseils réglés</span>
                  </div>
                  {p.roi_global != null && (
                    <div className={`mt-0.5 text-lg font-bold tabular-nums ${tone(p.roi_global)}`}>
                      ROI {signedPct(p.roi_global)}
                    </div>
                  )}
                  <div className="mt-2 space-y-1">
                    {Object.entries(p.type_weights || {}).slice(0, 6).map(([t, w]) => (
                      <div key={t} className="flex items-center gap-2 text-[10px]">
                        <span className="w-24 shrink-0 truncate text-gray-500">{t}</span>
                        <div className="relative h-1.5 flex-1 rounded-full bg-gray-100">
                          <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300" />
                          <div
                            className="absolute inset-y-0 rounded-full"
                            style={{
                              left: (w as number) >= 1 ? "50%" : `${50 - Math.min(Math.abs((w as number) - 1) * 100, 50)}%`,
                              width: `${Math.min(Math.abs((w as number) - 1) * 100, 50)}%`,
                              background: (w as number) >= 1 ? DIVERGING_POS : DIVERGING_NEG,
                            }}
                          />
                        </div>
                        <span className={`w-10 shrink-0 text-right font-mono font-semibold tabular-nums ${(w as number) >= 1 ? "text-emerald-600" : "text-red-600"}`}>
                          ×{(w as number).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* ROI par signal */}
      {(learning?.signaux?.length ?? 0) > 0 && (
        <Section
          title="Rendement réel par signal qualitatif"
          desc="Chaque signal détecté par l'analyse (forme, driver, terrain…) confronté au résultat encaissé. Seuls les signaux à 30 conseils minimum sont affichés."
        >
          <div className="space-y-1.5">
            {learning!.signaux.map((s: { signal: string; n: number; win_rate: number; roi: number }) => (
              <div key={s.signal} className="flex items-center gap-3 text-[11px]">
                <span className="w-40 shrink-0 truncate font-medium text-gray-700">{s.signal}</span>
                <div className="relative h-2 flex-1 rounded-full bg-gray-100">
                  <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300" />
                  <div
                    className="absolute inset-y-0 rounded-full"
                    style={{
                      left: s.roi >= 0 ? "50%" : `${50 - Math.min(Math.abs(s.roi) * 100, 50)}%`,
                      width: `${Math.min(Math.abs(s.roi) * 100, 50)}%`,
                      background: s.roi >= 0 ? DIVERGING_POS : DIVERGING_NEG,
                    }}
                  />
                </div>
                <span className={`w-14 shrink-0 text-right font-mono font-bold tabular-nums ${tone(s.roi)}`}>
                  {signedPct(s.roi * 100, 0)}
                </span>
                <span className="w-24 shrink-0 text-right tabular-nums text-gray-400">
                  {pct(s.win_rate * 100, 0)} · {num(s.n)}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Brier course par course + poids features */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Erreur course par course"
          desc="Brier de chaque course analysée, de la plus ancienne à la plus récente. Les points rouges sont les courses classées « surprise »."
          right={
            <div className="flex gap-1">
              {[15, 30, 50].map((n) => (
                <button
                  key={n}
                  onClick={() => setHistLimit(n)}
                  className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${histLimit === n ? "bg-gray-900 text-white" : "text-gray-400 hover:text-gray-700"}`}
                >
                  {n}
                </button>
              ))}
            </div>
          }
        >
          {loadingHistory || histPoints.length === 0 ? (
            <Empty>{loadingHistory ? "Chargement…" : "Aucune course analysée."}</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={histPoints} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="date" hide />
                <YAxis domain={[0, 0.5]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={40} tickFormatter={(v) => v.toFixed(2)} />
                <ReferenceLine y={0.25} stroke="#EF4444" strokeDasharray="4 4" label={{ value: "seuil critique", fontSize: 9, fill: "#EF4444", position: "insideTopRight" }} />
                <ReferenceLine y={0.18} stroke="#10B981" strokeDasharray="4 4" label={{ value: "cible", fontSize: 9, fill: "#10B981", position: "insideBottomRight" }} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} />} />
                <Line
                  type="monotone" dataKey="brier" name="Brier" stroke="#3B82F6" strokeWidth={1.5}
                  dot={(props: any) => {
                    const { cx, cy, payload, index } = props;
                    if (cx == null || cy == null || !payload) return <g key={index} />;
                    return (
                      <circle
                        key={index} cx={cx} cy={cy} r={payload.surprise ? 4 : 2}
                        fill={payload.surprise ? "#EF4444" : "#3B82F6"} stroke="#fff" strokeWidth={payload.surprise ? 1 : 0}
                      />
                    );
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Section>

        <Section
          title="Poids adaptatifs des features"
          desc="Ajustement appris en ligne, en plus des poids figés du modèle. Vert = la feature est renforcée, rouge = elle est atténuée."
        >
          {topFeatures.length === 0 ? (
            <Empty>Poids non disponibles — le tilt attend son volume minimal de courses.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(210, topFeatures.length * 22)}>
              <BarChart data={topFeatures} layout="vertical" margin={{ left: 4, right: 16, top: 4, bottom: 4 }}>
                <CartesianGrid {...GRID} horizontal={false} vertical />
                <XAxis type="number" tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => v.toFixed(2)} />
                <YAxis type="category" dataKey="name" width={116} tick={{ fontSize: 10, fill: "#6B7280" }} axisLine={axisLine} tickLine={tickLine} />
                <ReferenceLine x={0} stroke="#9CA3AF" />
                <Tooltip cursor={{ fill: "rgba(148,163,184,0.08)" }} content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} />} />
                <Bar dataKey="weight" name="Poids adaptatif" radius={[0, 3, 3, 0]} barSize={11}>
                  {topFeatures.map((f, i) => (
                    <Cell key={i} fill={f.weight > 0 ? DIVERGING_POS : DIVERGING_NEG} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Section>
      </div>

      {/* Biais contextuels */}
      <Section
        title="Biais contextuels détectés"
        desc="Contextes (hippodrome, discipline, terrain) où le modèle se trompe systématiquement dans le même sens. La correction est appliquée à l'inférence."
        right={
          biasRows.length > 0 ? (
            <button
              onClick={() => setShowBiasAll((v) => !v)}
              className="flex items-center gap-1 text-[11px] font-medium text-gray-500 hover:text-gray-900"
            >
              {showBiasAll ? <><ChevronUp className="h-3 w-3" />Réduire</> : <><ChevronDown className="h-3 w-3" />Tout voir</>}
            </button>
          ) : undefined
        }
      >
        {!biasMatrix ? (
          <Empty>Chargement…</Empty>
        ) : biasRows.length === 0 ? (
          <Empty>Aucun biais détecté — il en faut au moins 5 courses par contexte.</Empty>
        ) : (
          <div className="-mx-4 overflow-x-auto px-4">
            <table className="w-full min-w-[620px] text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 pr-3 text-left font-semibold">Contexte</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-left font-semibold">Terrain</th>
                  <th className="px-2 py-2 text-right font-semibold">Courses</th>
                  <th className="px-2 py-2 text-right font-semibold">Surprises</th>
                  <th className="px-2 py-2 text-right font-semibold">Brier moyen</th>
                  <th className="px-2 py-2 text-right font-semibold">Correction</th>
                </tr>
              </thead>
              <tbody>
                {biasRows.map((row, i) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="max-w-[180px] truncate py-2 pr-3 font-medium text-gray-700" title={row.contexte}>
                      {row.hippodrome ?? row.contexte}
                    </td>
                    <td className="px-2 py-2 text-gray-500">{row.discipline ?? "—"}</td>
                    <td className="px-2 py-2 text-gray-500">{row.terrain ?? "—"}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-gray-600">{num(row.nb_courses)}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-amber-600">{pct((row.taux_surprise ?? 0) * 100)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-gray-600">{row.brier_moyen?.toFixed(4) ?? "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono font-bold tabular-nums ${Math.abs(row.correction_factor ?? 0) > 0.08 ? ((row.correction_factor ?? 0) > 0 ? "text-red-600" : "text-blue-600") : "text-gray-400"}`}>
                      {(row.correction_factor ?? 0) > 0 ? "+" : ""}{(row.correction_factor ?? 0).toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Note>
          Correction positive = le contexte produit plus de surprises que prévu, les probabilités y
          sont aplaties. Correction négative = le favori y tient mieux qu&apos;ailleurs.
        </Note>
      </Section>

      {/* Journal */}
      <Section
        title={<span className="flex items-center gap-2"><Zap className="h-4 w-4 text-emerald-500" />Journal d&apos;apprentissage</span>}
        desc="Les dernières courses digérées par le moteur, avec l'ajustement de température qu'elles ont provoqué."
      >
        {loadingHistory ? (
          <Empty>Chargement…</Empty>
        ) : !history?.length ? (
          <Empty>Aucune course analysée.</Empty>
        ) : (
          <div className="-mx-4 max-h-[420px] overflow-auto px-4">
            <table className="w-full min-w-[620px] text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 pr-3 text-left font-semibold">Date</th>
                  <th className="px-2 py-2 text-left font-semibold">Hippodrome</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-right font-semibold">Brier</th>
                  <th className="px-2 py-2 text-right font-semibold">Proba du gagnant</th>
                  <th className="px-2 py-2 text-right font-semibold">Rang prédit</th>
                  <th className="px-2 py-2 text-right font-semibold">Δ température</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={h.log_id ?? i} className={`border-b border-gray-50 ${h.was_surprise ? "bg-red-50/40" : ""}`}>
                    <td className="py-2 pr-3 font-mono text-gray-500">
                      {h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "—"}
                    </td>
                    <td className="px-2 py-2 font-medium text-gray-700">{h.hippodrome ?? "—"}</td>
                    <td className="px-2 py-2 text-gray-500">{h.discipline ?? "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${(h.brier_score ?? 0) > 0.25 ? "text-red-600" : (h.brier_score ?? 0) < 0.18 ? "text-emerald-600" : "text-gray-700"}`}>
                      {h.brier_score?.toFixed(4) ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-gray-600">
                      {h.gagnant_proba_ia != null ? pct(h.gagnant_proba_ia * 100) : "—"}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {h.gagnant_rang_predit != null ? (
                        <span className={`font-bold ${h.gagnant_rang_predit === 1 ? "text-emerald-600" : h.gagnant_rang_predit <= 3 ? "text-amber-600" : "text-gray-400"}`}>
                          #{h.gagnant_rang_predit}
                        </span>
                      ) : "—"}
                      {h.was_surprise && <span className="ml-1 text-red-500" title="Course classée surprise">⚡</span>}
                    </td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${(h.temperature_update ?? 0) > 0 ? "text-red-600" : (h.temperature_update ?? 0) < 0 ? "text-emerald-600" : "text-gray-400"}`}>
                      {h.temperature_update != null ? `${h.temperature_update > 0 ? "+" : ""}${h.temperature_update.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
