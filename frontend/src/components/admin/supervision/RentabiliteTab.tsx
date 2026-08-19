"use client";

/**
 * Onglet « Rentabilité » — la courbe qu'on ne peut pas maquiller.
 *
 * Capital cumulé jour par jour sur les conseils réellement émis, drawdown vécu,
 * ROI glissant. Deux graphiques distincts plutôt qu'un double axe : superposer
 * un capital en euros et un ROI en pourcentage sur une même échelle laisse
 * choisir la pente qu'on veut montrer.
 *
 * Chaque courbe est tracée sur les gains RÉELS (trait plein) avec la variante
 * winsorisée à 50× la mise en pointillés. Afficher uniquement la winsorisée
 * mentait : le 19/07 (+4 306 € réels, un rapport à 4 526 €) apparaissait à
 * +280 €, et 4 jours bénéficiaires étaient dessinés en rouge.
 */

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CalendarDays, TrendingDown } from "lucide-react";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import {
  DIVERGING_NEG, DIVERGING_POS, Empty, Note, Section, StatTile,
  eur, num, pct, signedEur, signedPct, tone,
} from "./kit";
import type { RentabilitePayload } from "./types";

const PROFIL_COLORS: Record<string, string> = {
  Prudent: "#10B981",
  Modéré: "#3B82F6",
  Risqué: "#EF4444",
};

function jourCourt(iso: string) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

export default function RentabiliteTab({ data }: { data?: RentabilitePayload }) {
  if (!data) return <Empty>Chargement de la rentabilité…</Empty>;
  const serie = data.serie ?? [];
  if (serie.length === 0) {
    return <Empty>Aucun jour réglé sur cette fenêtre.</Empty>;
  }

  const r = data.resume;
  const chart = serie.map((s) => ({ ...s, label: jourCourt(s.jour) }));

  const profils = Object.keys(data.cumul_par_profil ?? {});
  const joursProfil = Array.from(
    new Set(profils.flatMap((p) => data.cumul_par_profil[p].map((x) => x.jour)))
  ).sort();
  const cumulChart = joursProfil.map((j) => {
    const row: Record<string, number | string> = { label: jourCourt(j) };
    for (const p of profils) {
      const pt = data.cumul_par_profil[p].find((x) => x.jour === j);
      // Gains réels uniquement : six courbes (réel + plafonné × 3 profils) sur
      // une même échelle ne se lisent plus. Le couple réel/plafonné est déjà
      // exposé sur le capital global, où l'écart se lit.
      if (pt) row[p] = pt.cumul;
    }
    return row;
  });
  const cap = data.gain_cap_mise;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile
          label="Résultat net réel"
          value={signedEur(r.net_total)}
          valueClass={tone(r.net_total)}
          sub={`sur ${eur(r.mise_totale)} engagés`}
          hint={`Gains réellement encaissés, sans plafond. Plafonnés à ${cap}× la mise : ${signedEur(r.net_total_winsor)}.`}
        />
        <StatTile
          label="ROI réel"
          value={signedPct(r.roi_pct)}
          valueClass={tone(r.roi_pct)}
          sub={`${signedPct(r.roi_winsor_pct)} plafonné · ${num(r.n_jours)} jours`}
          hint={`Le ROI plafonné à ${cap}× la mise coupe les rapports extrêmes : c'est la lecture prudente qui sert de verdict, pas l'argent réellement compté. L'écart entre les deux EST l'information.`}
        />
        <StatTile
          label="Jours positifs"
          value={pct(r.taux_jours_positifs_pct)}
          sub={`${num(r.jours_positifs)} / ${num(r.n_jours)} jours · ${num(r.jours_positifs_winsor)} plafonné`}
          icon={<CalendarDays className="h-3.5 w-3.5 text-gray-300" />}
          hint="Compté sur les gains réels : un jour où un gros rapport est tombé est un jour gagnant, même si le plafond le ramènerait sous zéro."
        />
        <StatTile
          label="Pire perte cumulée"
          value={eur(r.drawdown_max)}
          valueClass="text-red-600"
          sub={`depuis le plus haut · ${eur(r.drawdown_max_winsor)} plafonné`}
          icon={<TrendingDown className="h-3.5 w-3.5 text-gray-300" />}
          hint="Drawdown maximum : ce qu'un suiveur aurait vu fondre au pire moment, gains réels compris."
        />
        <StatTile
          label="Série perdante"
          value={`${num(r.serie_perdante_max_jours)} j`}
          sub={`plus longue suite négative · ${num(r.serie_perdante_max_jours_winsor)} j plafonné`}
        />
      </div>

      {/* Capital cumulé */}
      <Section
        title="Capital cumulé"
        desc={`Somme des résultats nets jour après jour, dans l'ordre réel des courses. Trait plein : les gains réellement encaissés — c'est la courbe qu'a vécue quelqu'un qui aurait suivi tous les conseils. Pointillés : la même série avec les gains coupés à ${cap}× la mise.`}
      >
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={chart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="capitalNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={DIVERGING_NEG} stopOpacity={0.05} />
                <stop offset="100%" stopColor={DIVERGING_NEG} stopOpacity={0.22} />
              </linearGradient>
            </defs>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} />
            <YAxis
              tick={axisTick} axisLine={axisLine} tickLine={tickLine}
              tickFormatter={(v) => `${Math.round(v)} €`} width={64}
            />
            <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="3 3" />
            <Tooltip content={<ChartTooltip valueFormatter={(v) => signedEur(v, 2)} />} />
            <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
            <Area
              type="monotone" dataKey="cumul_net" name="Capital réel"
              stroke={DIVERGING_NEG} strokeWidth={2} fill="url(#capitalNeg)" isAnimationActive={false}
            />
            <Line
              type="monotone" dataKey="cumul_net_winsor" name={`Plafonné à ${cap}× la mise`}
              stroke="#9CA3AF" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
        <Note>
          Une pente qui descend régulièrement n&apos;est pas un accident de parcours : c&apos;est le
          prélèvement PMU qui n&apos;est pas encore battu. C&apos;est précisément le chiffre que cette
          page existe pour rendre indiscutable. L&apos;écart entre les deux traits est la part du
          résultat qui tient à quelques rapports extrêmes — réels, mais non reproductibles.
        </Note>
      </Section>

      {/* Résultat quotidien + ROI glissant : deux échelles, deux graphiques */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Résultat par jour"
          desc="Barres vertes = jour bénéficiaire, rouges = jour perdant. Gains réels, sans plafond."
        >
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} />
              <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${v} €`} width={56} />
              <ReferenceLine y={0} stroke="#9CA3AF" />
              <Tooltip
                cursor={{ fill: "rgba(148,163,184,0.08)" }}
                content={<ChartTooltip valueFormatter={(v) => signedEur(v, 2)} />}
              />
              <Bar dataKey="net" name="Résultat du jour" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                {chart.map((c) => (
                  <Cell key={c.jour} fill={c.net >= 0 ? DIVERGING_POS : DIVERGING_NEG} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div className="rounded-lg bg-emerald-50 p-2">
              <div className="text-emerald-700">Meilleur jour</div>
              <div className="font-bold tabular-nums text-emerald-700">
                {signedEur(r.meilleur_jour?.net, 2)}
                <span className="ml-1 font-normal text-emerald-600/70">
                  {r.meilleur_jour ? jourCourt(r.meilleur_jour.jour) : ""}
                </span>
              </div>
              {r.meilleur_jour && r.meilleur_jour.net_winsor !== r.meilleur_jour.net && (
                <div className="mt-0.5 text-emerald-600/70">
                  {signedEur(r.meilleur_jour.net_winsor, 2)} une fois plafonné
                </div>
              )}
            </div>
            <div className="rounded-lg bg-red-50 p-2">
              <div className="text-red-700">Pire jour</div>
              <div className="font-bold tabular-nums text-red-700">
                {signedEur(r.pire_jour?.net, 2)}
                <span className="ml-1 font-normal text-red-600/70">
                  {r.pire_jour ? jourCourt(r.pire_jour.jour) : ""}
                </span>
              </div>
            </div>
          </div>
        </Section>

        <Section
          title="ROI glissant sur 14 jours"
          desc="Rendement des 14 derniers jours de courses, recalculé chaque jour. Lisse le bruit quotidien sans masquer une dérive."
        >
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} />
              <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${v} %`} width={48} />
              <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="3 3" label={{ value: "équilibre", fontSize: 9, fill: "#9CA3AF", position: "right" }} />
              <Tooltip content={<ChartTooltip valueFormatter={(v) => signedPct(v)} />} />
              <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
              <Line
                type="monotone" dataKey="roi_glissant_pct" name="ROI 14 jours (réel)"
                stroke="#3B82F6" strokeWidth={2} dot={false} connectNulls isAnimationActive={false}
              />
              <Line
                type="monotone" dataKey="roi_glissant_winsor_pct" name="plafonné"
                stroke="#9CA3AF" strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <Note>
            Objectif de survie : remonter au-dessus de la ligne d&apos;équilibre. Le prélèvement PMU
            moyen (15 à 30 % selon le type) est l&apos;écart à combler.
          </Note>
        </Section>
      </div>

      {/* Cumul par profil */}
      {profils.length > 0 && (
        <Section
          title="Capital cumulé par profil"
          desc="Prudent, Modéré, Risqué : trois politiques de mise sur les mêmes pronostics, gains réels. L'écart entre les courbes mesure ce que le profil ajoute, pas ce que le modèle prédit."
        >
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={cumulChart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} />
              <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${Math.round(v)} €`} width={64} />
              <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="3 3" />
              <Tooltip content={<ChartTooltip valueFormatter={(v) => signedEur(v, 2)} />} />
              <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
              {profils.map((p) => (
                <Line
                  key={p} type="monotone" dataKey={p} name={p}
                  stroke={PROFIL_COLORS[p] ?? "#6B7280"} strokeWidth={2} dot={false} connectNulls isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </Section>
      )}
    </div>
  );
}
