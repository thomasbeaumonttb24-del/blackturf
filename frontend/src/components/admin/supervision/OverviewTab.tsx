"use client";

/**
 * Onglet « Vue d'ensemble » — la réponse en dix secondes.
 *
 * Les phrases de synthèse ne sont pas rédigées à l'avance : elles sont dérivées
 * des chiffres reçus (meilleur type, écart brut/winsorisé, drawdown, delta du
 * modèle). Si une donnée manque, la phrase correspondante disparaît au lieu
 * d'être remplie avec une valeur par défaut.
 */

import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { ArrowUpRight, Brain, CircleDollarSign, Layers, ShieldAlert, Sparkles } from "lucide-react";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import {
  DIVERGING_NEG, DIVERGING_POS, Empty, Note, Section, StatTile, VerdictBadge,
  eur, num, pct, signedEur, signedPct, tone,
} from "./kit";
import type { AlgoEvolutionPayload, ParisPayload, RentabilitePayload } from "./types";

interface Victoire {
  course_id: string; code: string | null; hippodrome: string;
  date: string | null; profil: string; net: number;
}

function jourCourt(iso: string) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/** Constats dérivés des données reçues — jamais du texte écrit d'avance. */
function constats(paris?: ParisPayload, renta?: RentabilitePayload, algo?: AlgoEvolutionPayload): string[] {
  const out: string[] = [];
  if (paris?.global?.roi_pct != null && paris.global.n_paris) {
    out.push(
      `Sur ${num(paris.global.n_paris)} paris réglés (${num(paris.global.n_courses)} courses), ` +
      `${signedEur(paris.global.net)} ont réellement été encaissés pour ${eur(paris.global.mise)} engagés ` +
      `(${signedPct(paris.global.roi_brut_pct)}). Une fois les gains plafonnés à 50× la mise — la lecture ` +
      `qui sert de verdict parce qu'un rapport isolé ne prouve rien — le rendement est de ` +
      `${signedPct(paris.global.roi_pct)}, soit ${signedEur(paris.global.net_winsorise)}.`
    );
  }
  const fiables = (paris?.types ?? []).filter((t) => t.verdict !== "insuffisant");
  if (fiables.length) {
    const best = fiables.reduce((a, b) => ((a.roi_pct ?? -999) >= (b.roi_pct ?? -999) ? a : b));
    const worst = fiables.reduce((a, b) => ((a.roi_pct ?? 999) <= (b.roi_pct ?? 999) ? a : b));
    out.push(
      `Parmi les types dont l'échantillon suffit, le moins coûteux est ${best.type} ` +
      `(${signedPct(best.roi_pct)}, ${num(best.n_gagnants)} gagnants) et le plus coûteux ${worst.type} ` +
      `(${signedPct(worst.roi_pct)}).`
    );
  }
  const trompeur = (paris?.types ?? [])
    .filter((t) => t.n_paris >= 100 && t.roi_brut_pct != null && t.roi_pct != null)
    .map((t) => ({ t, ecart: (t.roi_brut_pct as number) - (t.roi_pct as number) }))
    .sort((a, b) => b.ecart - a.ecart)[0];
  if (trompeur && trompeur.ecart > 20) {
    out.push(
      `${trompeur.t.type} affiche ${signedPct(trompeur.t.roi_brut_pct)} brut mais ` +
      `${signedPct(trompeur.t.roi_pct)} une fois les gains plafonnés à 50× la mise : ce rendement ` +
      `tient à quelques rapports extrêmes, pas à un avantage.`
    );
  }
  if (renta?.resume?.drawdown_max != null && renta.resume.n_jours) {
    out.push(
      `La pire perte cumulée observée est de ${eur(renta.resume.drawdown_max)}, avec ` +
      `${num(renta.resume.serie_perdante_max_jours)} jours négatifs consécutifs au maximum sur ` +
      `${num(renta.resume.n_jours)} jours de courses.`
    );
  }
  if (algo?.active && algo.delta_vs_precedente?.walk_forward_auc != null) {
    const d = algo.delta_vs_precedente.walk_forward_auc;
    out.push(
      `Le modèle actif (v${algo.active.version}) affiche une AUC walk-forward de ` +
      `${algo.active.walk_forward_auc?.toFixed(4)}, ${d >= 0 ? "en hausse de" : "en baisse de"} ` +
      `${Math.abs(d).toFixed(4)} par rapport à la version précédente.`
    );
  }
  return out;
}

export default function OverviewTab({
  paris, renta, algo, victoires, onGoTo,
}: {
  paris?: ParisPayload;
  renta?: RentabilitePayload;
  algo?: AlgoEvolutionPayload;
  victoires?: Victoire[];
  onGoTo: (tab: string) => void;
}) {
  const g = paris?.global;
  const r = renta?.resume;
  const chart = (renta?.serie ?? []).map((s) => ({ ...s, label: jourCourt(s.jour) }));
  const phrases = constats(paris, renta, algo);
  const familles = (paris?.familles ?? []).filter((f) => f.n_paris >= 20).slice(0, 6);

  return (
    <div className="space-y-5">
      {/* KPI principaux */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile
          label="Conseils réglés"
          value={num(g?.n_paris)}
          sub={`${num(g?.n_courses)} courses couvertes`}
          icon={<Layers className="h-3.5 w-3.5 text-gray-300" />}
        />
        <StatTile
          label="Capital réel"
          value={signedEur(r?.net_total)}
          valueClass={tone(r?.net_total)}
          sub={`${eur(r?.mise_totale)} engagés · ${signedEur(r?.net_total_winsor)} plafonné`}
          icon={<CircleDollarSign className="h-3.5 w-3.5 text-gray-300" />}
          hint="Gains réellement encaissés, sans plafond — le ROI winsorisé de la tuile voisine coupe les rapports extrêmes pour rendre un verdict."
        />
        <StatTile
          label="ROI winsorisé"
          value={signedPct(g?.roi_pct)}
          valueClass={tone(g?.roi_pct)}
          sub={g?.ic90_roi_pct ? `IC 90 % ${signedPct(g.ic90_roi_pct[0], 0)} → ${signedPct(g.ic90_roi_pct[1], 0)}` : "—"}
          footer={<VerdictBadge verdict={g?.verdict} />}
        />
        <StatTile
          label="Modèle actif"
          value={algo?.active ? `v${algo.active.version}` : "—"}
          sub={`AUC walk-forward ${algo?.active?.walk_forward_auc?.toFixed(4) ?? "—"}`}
          icon={<Brain className="h-3.5 w-3.5 text-gray-300" />}
        />
        <StatTile
          label="Pire perte cumulée"
          value={eur(r?.drawdown_max)}
          valueClass="text-red-600"
          sub={`${num(r?.serie_perdante_max_jours)} jours perdants d'affilée`}
          icon={<ShieldAlert className="h-3.5 w-3.5 text-gray-300" />}
        />
      </div>

      {/* Ce que disent les chiffres */}
      <Section
        title={<span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-amber-500" />Ce que disent les chiffres</span>}
        desc="Constats calculés à partir des données ci-dessous, recalculés à chaque rafraîchissement."
      >
        {phrases.length === 0 ? (
          <Empty>Pas encore assez de données réglées pour formuler un constat.</Empty>
        ) : (
          <ul className="space-y-2.5">
            {phrases.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-gray-700">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        {/* Capital cumulé */}
        <Section
          className="xl:col-span-2"
          title="Capital cumulé"
          desc="Résultat net additionné jour après jour sur les conseils réellement émis, gains réels sans plafond."
          right={
            <button onClick={() => onGoTo("rentabilite")} className="flex items-center gap-1 text-[11px] font-medium text-amber-600 hover:text-amber-700">
              Détail <ArrowUpRight className="h-3 w-3" />
            </button>
          }
        >
          {chart.length === 0 ? (
            <Empty>Aucun jour réglé sur cette fenêtre.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="ovCapital" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={DIVERGING_NEG} stopOpacity={0.04} />
                    <stop offset="100%" stopColor={DIVERGING_NEG} stopOpacity={0.2} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={26} />
                <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${Math.round(v)} €`} width={62} />
                <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="3 3" />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => signedEur(v, 2)} />} />
                <Area type="monotone" dataKey="cumul_net" name="Capital cumulé" stroke={DIVERGING_NEG} strokeWidth={2} fill="url(#ovCapital)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Section>

        {/* Familles de paris */}
        <Section
          title="Par famille de pari"
          desc="Regroupement PMU : les variantes d'un même pari partagent règle et prélèvement."
          right={
            <button onClick={() => onGoTo("paris")} className="flex items-center gap-1 text-[11px] font-medium text-amber-600 hover:text-amber-700">
              Détail <ArrowUpRight className="h-3 w-3" />
            </button>
          }
        >
          {familles.length === 0 ? (
            <Empty>Pas encore de famille à 20 paris réglés.</Empty>
          ) : (
            <div className="space-y-3">
              {familles.map((f) => (
                <div key={f.famille}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium text-gray-700">{f.famille}</span>
                    <span className={`font-mono font-bold tabular-nums ${tone(f.roi_pct)}`}>
                      {signedPct(f.roi_pct)}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded-full bg-gray-100">
                      <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300" />
                      <div
                        className="absolute inset-y-0 rounded-full"
                        style={{
                          left: (f.roi_pct ?? 0) >= 0 ? "50%" : `${50 - Math.min(Math.abs(f.roi_pct ?? 0) / 2, 50)}%`,
                          width: `${Math.min(Math.abs(f.roi_pct ?? 0) / 2, 50)}%`,
                          background: (f.roi_pct ?? 0) >= 0 ? DIVERGING_POS : DIVERGING_NEG,
                        }}
                      />
                    </div>
                    <span className="w-24 shrink-0 text-right text-[10px] tabular-nums text-gray-400">
                      {num(f.n_paris)} paris · {pct(f.part_mise_pct, 0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
          <Note>Chiffre de droite : nombre de paris et part de la mise totale.</Note>
        </Section>
      </div>

      {/* Dernières victoires */}
      {(victoires?.length ?? 0) > 0 && (
        <Section
          title="Dernières courses gagnantes"
          desc="Courses où le plan d'un profil est ressorti net positif, sur rapports PMU réels. Cliquable."
        >
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {victoires!.slice(0, 12).map((v, i) => (
              <a
                key={i}
                href={`/courses/${v.course_id}`}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11px] transition-colors hover:bg-amber-50/60"
              >
                <span className="w-10 shrink-0 tabular-nums text-gray-400">
                  {v.date ? new Date(v.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—"}
                </span>
                <span className="w-12 shrink-0 font-mono font-semibold text-gray-700">{v.code ?? "—"}</span>
                <span className="flex-1 truncate text-gray-500">{v.hippodrome}</span>
                <span className="shrink-0 text-[10px] text-gray-400">{v.profil}</span>
                <span className="w-16 shrink-0 text-right font-mono font-bold tabular-nums text-emerald-600">
                  {signedEur(v.net, 2)}
                </span>
              </a>
            ))}
          </div>
          <Note>
            Une liste de victoires ne mesure rien à elle seule — elle est là pour vérifier des cas
            concrets, la mesure reste le ROI de l&apos;ensemble.
          </Note>
        </Section>
      )}
    </div>
  );
}
