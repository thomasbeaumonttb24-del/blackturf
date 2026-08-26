"use client";

/**
 * Onglet « Types de paris » — la visibilité qui manquait.
 *
 * Chaque chiffre vient de `ml/bet_type_analytics.py`, donc de conseils
 * réellement émis avant le départ et réglés sur les rapports PMU. Trois
 * conventions sont assumées à l'écran plutôt que cachées :
 *   · un MONTANT en euros est toujours l'argent réellement encaissé ; seuls les
 *     ROI qui servent de verdict sont WINSORISÉS à 50× la mise (brut à côté) ;
 *   · un verdict exige 150 gagnants, pas 150 paris ;
 *   · le test de robustesse montre ce que devient le ROI sans les plus gros gains.
 */

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowDownRight, Coins, Scale, Target } from "lucide-react";
import {
  CHART_PALETTE, ChartTooltip, GRID, axisLine, axisTick, tickLine,
} from "@/components/charts/chart-kit";
import {
  DIVERGING_NEG, DIVERGING_POS, Empty, Note, PolarityBar, Section, StatTile,
  VerdictBadge, eur, num, pct, signedEur, signedPct, tone,
} from "./kit";
import type { ParisPayload, TypeRow } from "./types";

const ROI_MAX_BAR = 60; // échelle des barres de polarité du tableau
// Rampe séquentielle mono-teinte (ambre de marque), du plus au moins engagé.
const MISE_RAMP = ["#B45309", "#D97706", "#F59E0B", "#FBBF24", "#FCD34D",
                   "#FDE68A", "#FEF08A", "#FEF3C7", "#FEF9E7", "#FFFBEB"];
// Sous ce nombre de paris dans la semaine, le ROI hebdomadaire d'un type est du
// bruit pur : un seul rapport le fait passer de -100 % à +600 %. La série est
// alors coupée (trou) au lieu d'écraser l'échelle des types à fort volume.
const MIN_PARIS_SEMAINE = 30;
// Un croisement profil × type sous ce nombre de gagnants n'est pas colorié :
// un « +140 % » sur 7 gagnants ne doit pas se lire comme une bonne nouvelle.
const MIN_GAGNANTS_CELLULE = 150;

export default function ParisTab({ data }: { data?: ParisPayload }) {
  const [selected, setSelected] = useState<string | null>(null);

  const types = data?.types ?? [];
  // Le type analysé par défaut est le plus joué : la liste est déjà triée par mise.
  const actif: TypeRow | undefined = types.find((t) => t.type === selected) ?? types[0];

  if (!data) {
    return <Empty>Chargement des chiffres par type de pari…</Empty>;
  }
  if (types.length === 0) {
    return (
      <Empty>
        Aucun conseil réglé sur cette fenêtre. Élargissez la période — rien n&apos;est
        extrapolé à partir d&apos;une fenêtre vide.
      </Empty>
    );
  }

  const g = data.global;
  // Trié du meilleur au pire, donc de haut en bas : l'œil descend la liste dans
  // l'ordre du classement, sans avoir à relire les valeurs.
  const roiChart = types
    .filter((t) => t.n_paris >= 20)
    .map((t) => ({
      type: t.type,
      roi: t.roi_pct ?? 0,
      // Barre pâle : le chiffre est affiché mais l'échantillon ne le rend pas concluant.
      fiable: t.verdict !== "insuffisant",
    }))
    .sort((a, b) => b.roi - a.roi);
  // L'axe part toujours de 0 : sans ça, une série entièrement négative se lit
  // comme si le zéro était au bord droit du graphique.
  const roiMin = Math.min(0, ...roiChart.map((r) => r.roi));
  const roiMax = Math.max(0, ...roiChart.map((r) => r.roi));

  const miseChart = types.slice(0, 10).map((t) => ({
    type: t.type,
    mise: t.mise ?? 0,
    part: t.part_mise_pct ?? 0,
    net: t.net ?? 0,
  }));

  const robust = actif?.robustesse ?? [];
  const robustChart = [
    { label: "tel quel", roi: actif?.roi_pct ?? null, n: actif?.n_paris ?? 0 },
    ...robust.map((r) => ({
      label: `sans les ${r.retires}`,
      roi: r.roi_pct,
      n: r.n_restants,
    })),
  ];

  const serieKeys = data.types_series ?? [];
  // Une semaine à moins de 30 paris sur un type est mise à null : la ligne
  // s'interrompt au lieu de faire un pic de +600 % qui aplatit tout le reste.
  const serie = (data.serie_hebdo ?? []).map((row) => {
    const clean: Record<string, number | string | null> = { semaine: row.semaine, debut: row.debut };
    for (const k of serieKeys) {
      const n = row[`n::${k}`];
      clean[`roi::${k}`] = typeof n === "number" && n >= MIN_PARIS_SEMAINE ? row[`roi::${k}`] : null;
      clean[`n::${k}`] = n ?? null;
    }
    return clean;
  });
  const semainesTronquees = (data.serie_hebdo ?? []).reduce((acc, row) => acc + serieKeys.filter(
    (k) => typeof row[`n::${k}`] === "number" && (row[`n::${k}`] as number) < MIN_PARIS_SEMAINE
  ).length, 0);

  return (
    <div className="space-y-5">
      {/* ── Bandeau global ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile
          label="Paris réglés"
          value={num(g.n_paris)}
          sub={`${num(g.n_courses)} courses · ${num(g.n_gagnants)} gagnants`}
          icon={<Target className="h-3.5 w-3.5 text-gray-300" />}
        />
        <StatTile
          label="Engagé"
          value={eur(g.mise)}
          sub={`mise moyenne ${eur(g.mise_moyenne, 2)}`}
          icon={<Coins className="h-3.5 w-3.5 text-gray-300" />}
        />
        <StatTile
          label="Résultat net réel"
          value={signedEur(g.net)}
          valueClass={tone(g.net)}
          sub={`${signedEur(g.net_winsorise)} plafonné`}
          hint="Argent réellement encaissé. La version plafonnée (gains coupés à 50× la mise) sert aux verdicts, pas au comptage."
        />
        <StatTile
          label="ROI winsorisé"
          value={signedPct(g.roi_pct)}
          valueClass={tone(g.roi_pct)}
          sub={
            g.ic90_roi_pct
              ? `IC 90 % ${signedPct(g.ic90_roi_pct[0])} → ${signedPct(g.ic90_roi_pct[1])}`
              : "intervalle non calculable"
          }
          hint="Rendement pour 100 € engagés, gains plafonnés à 50× la mise."
        />
        <StatTile
          label="Taux de réussite"
          value={pct(g.hit_rate)}
          sub={`gain médian ${eur(g.gain_median, 2)}`}
          footer={<VerdictBadge verdict={g.verdict} />}
        />
      </div>

      {/* ── ROI par type ───────────────────────────────────────── */}
      <Section
        title="Rendement par type de pari"
        desc="ROI winsorisé à 50× la mise, sur les conseils réglés. Un type sous 150 gagnants est affiché mais jamais tranché."
        right={
          <span className="text-[10px] text-gray-600">
            {types.length} types joués · fenêtre {data.fenetre_jours ?? "complète"}
            {data.fenetre_jours ? " j" : ""}
          </span>
        }
      >
        {roiChart.length === 0 ? (
          <Empty>Aucun type n&apos;atteint 20 paris réglés sur la fenêtre.</Empty>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(220, roiChart.length * 30)}>
            <BarChart data={roiChart} layout="vertical" margin={{ left: 4, right: 52, top: 4, bottom: 4 }}>
              <CartesianGrid {...GRID} horizontal={false} vertical />
              <XAxis
                type="number" tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                tickFormatter={(v) => `${v} %`}
                domain={[Math.floor((roiMin - 8) / 10) * 10, Math.ceil((roiMax + 8) / 10) * 10]}
              />
              <YAxis
                type="category" dataKey="type" width={132} interval={0}
                tick={{ fontSize: 10, fill: "#6B7280", fontWeight: 500 }}
                axisLine={axisLine} tickLine={tickLine}
              />
              <ReferenceLine x={0} stroke="#6B7280" strokeWidth={1.5} />
              <Tooltip
                cursor={{ fill: "rgba(148,163,184,0.08)" }}
                content={<ChartTooltip valueFormatter={(v) => signedPct(v)} />}
              />
              <Bar dataKey="roi" name="ROI winsorisé" radius={[0, 3, 3, 0]} barSize={13} isAnimationActive={false}>
                {roiChart.map((r) => (
                  <Cell
                    key={r.type}
                    fill={r.roi >= 0 ? DIVERGING_POS : DIVERGING_NEG}
                    fillOpacity={r.fiable ? 1 : 0.35}
                  />
                ))}
                {/* Étiquette du côté OPPOSÉ à la barre : sur une série négative,
                    `position="right"` collerait tous les nombres sur l'axe zéro. */}
                <LabelList
                  dataKey="roi"
                  position="left"
                  formatter={(v: number) => signedPct(v, 0)}
                  style={{ fontSize: 10, fontWeight: 700, fill: "#374151" }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-gray-600">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: DIVERGING_POS }} />
            gain
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: DIVERGING_NEG }} />
            perte
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-gray-400 opacity-40" />
            barre pâle = moins de 150 gagnants, chiffre non concluant
          </span>
        </div>
      </Section>

      {/* ── Où part l'argent + robustesse ──────────────────────── */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Où part l'argent"
          desc="Répartition de la mise engagée. Un type peut peser lourd sans rien rapporter — c'est ce que la colonne « net » montre."
        >
          <div className="space-y-2.5">
            {miseChart.map((m, i) => (
              <div key={m.type} className="flex items-center gap-3 text-xs">
                <span className="w-28 shrink-0 truncate font-medium text-gray-700">{m.type}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                  {/* Une part de mise est une GRANDEUR, pas une identité : une
                      seule teinte qui s'éclaircit, jamais un arc-en-ciel qui
                      suggérerait des catégories différentes. */}
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(m.part, 1)}%`,
                      background: MISE_RAMP[Math.min(i, MISE_RAMP.length - 1)],
                    }}
                  />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums text-gray-600">
                  {pct(m.part, 0)}
                </span>
                <span className="w-16 shrink-0 text-right font-mono font-bold tabular-nums">
                  <span className={tone(m.net)}>{signedEur(m.net)}</span>
                </span>
              </div>
            ))}
          </div>
          <Note>
            Barre = part de la mise totale ({eur(data.global.mise)} engagés). Chiffre de droite =
            résultat net réellement encaissé sur le type.
          </Note>
        </Section>

        <Section
          title={<span className="flex items-center gap-2"><Scale className="h-4 w-4 text-amber-700" />Test de robustesse — {actif?.type}</span>}
          desc="Le ROI recalculé en retirant les plus gros gains. S'il s'effondre, le rendement tenait à une poignée de coups, pas à un avantage."
          right={
            <select
              value={actif?.type ?? ""}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-700"
            >
              {types.map((t) => (
                <option key={t.type} value={t.type}>{t.type}</option>
              ))}
            </select>
          }
        >
          {robustChart.length <= 1 ? (
            <Empty>Trop peu de paris sur ce type pour retirer quoi que ce soit.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={robustChart} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis
                  tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                  tickFormatter={(v) => `${v} %`}
                />
                <ReferenceLine y={0} stroke="#4B5563" />
                <Tooltip
                  cursor={{ fill: "rgba(148,163,184,0.08)" }}
                  content={<ChartTooltip valueFormatter={(v) => signedPct(v)} />}
                />
                <Bar dataKey="roi" name="ROI" radius={[4, 4, 0, 0]} barSize={44} isAnimationActive={false}>
                  {robustChart.map((r, i) => (
                    <Cell key={i} fill={(r.roi ?? 0) >= 0 ? DIVERGING_POS : DIVERGING_NEG} />
                  ))}
                  <LabelList
                    dataKey="roi" position="top"
                    formatter={(v: number) => signedPct(v, 0)}
                    style={{ fontSize: 11, fontWeight: 700, fill: "#374151" }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          {actif && (
            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
              <div className="rounded-lg bg-gray-50 p-2">
                <div className="text-gray-600">ROI brut</div>
                <div className={`font-bold tabular-nums ${tone(actif.roi_brut_pct)}`}>
                  {signedPct(actif.roi_brut_pct)}
                </div>
              </div>
              <div className="rounded-lg bg-gray-50 p-2">
                <div className="text-gray-600">ROI winsorisé</div>
                <div className={`font-bold tabular-nums ${tone(actif.roi_pct)}`}>
                  {signedPct(actif.roi_pct)}
                </div>
              </div>
              <div className="rounded-lg bg-gray-50 p-2">
                <div className="text-gray-600">Plus gros gain</div>
                <div className="font-bold tabular-nums text-gray-700">{eur(actif.gain_max)}</div>
              </div>
              <div className="rounded-lg bg-gray-50 p-2">
                <div className="text-gray-600">Gagnants</div>
                <div className="font-bold tabular-nums text-gray-700">
                  {num(actif.n_gagnants)} / {num(actif.n_gagnants_requis ?? 150)} requis
                </div>
              </div>
            </div>
          )}
          {actif && Math.abs((actif.roi_brut_pct ?? 0) - (actif.roi_pct ?? 0)) > 15 && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] text-amber-800">
              <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
              <span>
                Écart de {pct(Math.abs((actif.roi_brut_pct ?? 0) - (actif.roi_pct ?? 0)), 0)} entre brut
                et winsorisé : le rendement apparent de ce type repose sur des rapports extrêmes.
                Le chiffre à retenir est le winsorisé.
              </span>
            </div>
          )}
        </Section>
      </div>

      {/* ── Fiche PMU du type sélectionné ──────────────────────── */}
      {actif?.reference && (
        <Section
          title={`Fiche PMU — ${actif.reference.famille}`}
          desc={actif.reference.a_trouver}
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile
              label="Prélèvement PMU"
              value={pct(actif.reference.prelevement_pct)}
              sub="part retirée du pool avant partage"
            />
            <StatTile
              label="Mise de base"
              value={eur(actif.reference.mise_base, 2)}
              sub={`champ minimal ${actif.reference.partants_min} partants`}
            />
            <StatTile
              label="Fréquence d'offre"
              value={pct(actif.reference.frequence_offre_pct)}
              sub="part des courses qui le proposent"
            />
            <StatTile
              label="Notre taux de réussite"
              value={pct(actif.hit_rate)}
              sub={`${num(actif.n_gagnants)} gagnants sur ${num(actif.n_paris)} paris`}
            />
          </div>
          <p className="mt-3 rounded-lg bg-gray-50 p-3 text-[11px] leading-relaxed text-gray-600">
            {actif.reference.quand_le_jouer}
          </p>
          <Note>
            Prélèvement et fréquence d&apos;offre viennent de `services/pmu_paris_reference.py`,
            mesurés sur nos propres conseils réglés.
          </Note>
        </Section>
      )}

      {/* ── Évolution hebdomadaire ─────────────────────────────── */}
      <Section
        title="Évolution semaine par semaine"
        desc="ROI winsorisé par type. Une semaine sans pari sur un type laisse un trou : la ligne n'est jamais inventée entre deux points."
      >
        {serie.length < 2 ? (
          <Empty>Moins de deux semaines de conseils réglés sur cette fenêtre.</Empty>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={serie} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis
                  tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                  tickFormatter={(v) => `${v} %`}
                />
                <ReferenceLine y={0} stroke="#4B5563" strokeDasharray="3 3" />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => signedPct(v)} />} />
                <Legend
                  verticalAlign="bottom" height={30}
                  wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                  formatter={(value: string) => value.replace("roi::", "")}
                />
                {serieKeys.map((k, i) => (
                  <Line
                    key={k}
                    type="monotone"
                    dataKey={`roi::${k}`}
                    name={k}
                    stroke={CHART_PALETTE[i % CHART_PALETTE.length]}
                    strokeWidth={2}
                    dot={{ r: 2.5 }}
                    connectNulls={false} isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
            <Note>
              Chaque point agrège tous les paris de ce type sur la semaine, et n&apos;est tracé
              qu&apos;à partir de {MIN_PARIS_SEMAINE} paris — en dessous, un seul rapport ferait
              passer la courbe de −100 % à +600 %.
              {semainesTronquees > 0 && ` ${semainesTronquees} point${semainesTronquees > 1 ? "s ont" : " a"} été retiré${semainesTronquees > 1 ? "s" : ""} pour cette raison : la ligne s'interrompt, elle n'est jamais lissée par-dessus.`}
            </Note>
          </>
        )}
      </Section>

      {/* ── Tableau détaillé ───────────────────────────────────── */}
      <Section
        title="Détail par type"
        desc="Cliquez une ligne pour l'analyser au-dessus."
      >
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[820px] text-xs">
            <thead>
              <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-600">
                <th className="py-2 pr-3 text-left font-semibold">Type</th>
                <th className="px-2 py-2 text-right font-semibold">Paris</th>
                <th className="px-2 py-2 text-right font-semibold">Gagnants</th>
                <th className="px-2 py-2 text-right font-semibold">Réussite</th>
                <th className="px-2 py-2 text-right font-semibold">Engagé</th>
                <th className="px-2 py-2 text-right font-semibold">Net réel</th>
                <th className="px-2 py-2 text-right font-semibold">ROI brut</th>
                <th className="px-2 py-2 text-right font-semibold">ROI winsorisé</th>
                <th className="w-24 px-2 py-2 text-left font-semibold">Polarité</th>
                <th className="px-2 py-2 text-right font-semibold">IC 90 %</th>
                <th className="py-2 pl-2 text-left font-semibold">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {types.map((t) => (
                <tr
                  key={t.type}
                  onClick={() => setSelected(t.type)}
                  className={`cursor-pointer border-b border-gray-50 transition-colors hover:bg-amber-50/40 ${
                    actif?.type === t.type ? "bg-amber-50/60" : ""
                  }`}
                >
                  <td className="py-2 pr-3 font-medium text-gray-800">{t.type}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-600">{num(t.n_paris)}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-600">{num(t.n_gagnants)}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-600">{pct(t.hit_rate)}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-600">{eur(t.mise)}</td>
                  <td className={`px-2 py-2 text-right font-mono font-bold tabular-nums ${tone(t.net)}`}>
                    {signedEur(t.net)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-gray-600">
                    {signedPct(t.roi_brut_pct)}
                  </td>
                  <td className={`px-2 py-2 text-right font-mono font-bold tabular-nums ${tone(t.roi_pct)}`}>
                    {signedPct(t.roi_pct)}
                  </td>
                  <td className="px-2 py-2">
                    <PolarityBar value={t.roi_pct ?? null} max={ROI_MAX_BAR} />
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-[10px] text-gray-600">
                    {t.ic90_roi_pct
                      ? `${signedPct(t.ic90_roi_pct[0], 0)} → ${signedPct(t.ic90_roi_pct[1], 0)}`
                      : "—"}
                  </td>
                  <td className="py-2 pl-2">
                    <VerdictBadge verdict={t.verdict} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          {data.source}. Gains plafonnés à {data.gain_cap_mise}× la mise ;{" "}
          {data.min_gagnants_verdict} gagnants minimum avant tout verdict.
        </Note>
      </Section>

      {/* ── Matrice profil × type ──────────────────────────────── */}
      <MatriceProfil data={data} />
    </div>
  );
}

function MatriceProfil({ data }: { data: ParisPayload }) {
  const cells = data.matrice_profil_type ?? [];
  if (cells.length === 0) return null;

  const profils = Array.from(new Set(cells.map((c) => c.profil)));
  const typesM = data.types_series ?? [];
  const key = (p: string, t: string) => cells.find((c) => c.profil === p && c.type === t);

  return (
    <Section
      title="Croisement profil × type de pari"
      desc="Le même type de pari ne rend pas la même chose selon le profil qui le sélectionne — c'est là que se voit ce que le moteur de mise apporte (ou coûte)."
    >
      <div className="-mx-4 overflow-x-auto px-4">
        <table className="w-full min-w-[640px] text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-600">
              <th className="py-2 pr-3 text-left font-semibold">Profil</th>
              {typesM.map((t) => (
                <th key={t} className="px-2 py-2 text-right font-semibold">{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {profils.map((p) => (
              <tr key={p} className="border-b border-gray-50">
                <td className="py-2.5 pr-3 font-semibold text-gray-800">{p}</td>
                {typesM.map((t) => {
                  const c = key(p, t);
                  if (!c) {
                    return <td key={t} className="px-2 py-2.5 text-right text-gray-300">—</td>;
                  }
                  // Sous le seuil de gagnants, la cellule reste en gris : la
                  // couleur est un verdict, et il n'y en a pas à ce volume.
                  const solide = c.n_gagnants >= MIN_GAGNANTS_CELLULE;
                  return (
                    <td key={t} className="px-2 py-2.5 text-right">
                      <div className={`font-mono text-xs font-bold tabular-nums ${solide ? tone(c.roi_pct) : "text-gray-600"}`}>
                        {signedPct(c.roi_pct, 0)}
                      </div>
                      <div className="text-[10px] tabular-nums text-gray-600">
                        {num(c.n_paris)} paris · {num(c.n_gagnants)} gagn.
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        <ArrowDownRight className="inline h-3 w-3" /> Les cellules en gris comptent moins de{" "}
        {MIN_GAGNANTS_CELLULE} gagnants : leur ROI est affiché pour être suivi, jamais coloré, même
        largement positif. Une cellule vide = ce profil n&apos;a jamais joué ce type.
      </Note>
    </Section>
  );
}
