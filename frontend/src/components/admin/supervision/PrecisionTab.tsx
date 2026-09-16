"use client";

/**
 * Onglet « Précision » — l'algorithme progresse-t-il sur les arrivées réelles ?
 *
 * Chaque course terminée est jugée sur ce qui a RÉELLEMENT été servi avant le départ
 * (dernier calcul à T-10), contre l'arrivée officielle, face au marché (cote figée au
 * même instant) et au modèle technique en observation. Calculé chaque nuit et
 * persisté (`ml/suivi_precision.py`) : rien n'est estimé à l'affichage, une mesure
 * absente s'affiche « — ».
 */

import { useState } from "react";
import useSWR from "swr";
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { adminApi } from "@/lib/api";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import { Segments } from "@/components/admin/ui";
import { Empty, Note, Section, StatTile, num, pct } from "./kit";

type Ecart = { moyenne: number | null; ic95: [number, number] | null; n: number; conclusif?: boolean };

interface Cumul {
  n_courses: number;
  n1_gagne_servi: number | null;
  favori_gagne_marche: number | null;
  gagnant_dans_top3_servi: number | null;
  auc_servi: number | null;
  auc_marche: number | null;
  classement_vs_marche: Ecart;
  cote_juste_vs_marche: Ecart;
  placement_logloss_servi: number | null;
  top3_annonce_juste_servi: number | null;
  technique: {
    n_courses: number;
    n1_gagne: number | null;
    auc: number | null;
    classement_vs_servi: Ecart;
    cote_juste_vs_servi: Ecart;
    placement_logloss: number | null;
  };
  simple_gagnant_n1: { paris: number; roi: number; roi_winsorise: number } | null;
  calibration_cote_juste: Array<{ tranche: string; partants: number; annonce: number; realise: number; victoires: number }>;
  valeurs_detectees: Array<{ niveau: number; paris: number; gagnants: number; roi: number; roi_winsorise: number }>;
}

interface SuiviPayload {
  mesure_disponible: boolean;
  pourquoi?: string;
  premier_jour?: string;
  dernier_jour?: string;
  par_jour?: Array<{
    jour: string; courses: number; courses_7j: number;
    n1_gagne_7j: number | null; favori_gagne_7j: number | null; n1_gagne_technique_7j: number | null;
    cote_juste_vs_marche_7j: number | null; classement_vs_marche_7j: number | null;
    technique_vs_servi_7j: number | null;
    placement_logloss_7j: number | null; placement_logloss_technique_7j: number | null;
  }>;
  par_semaine?: Array<Cumul & { semaine: string }>;
  fenetres?: Record<"7j" | "30j" | "tout", Cumul>;
}

const SEGMENTS = [
  { key: "tout", label: "Toutes" },
  { key: "attele", label: "Attelé" },
  { key: "plat", label: "Plat" },
  { key: "monte", label: "Monté" },
  { key: "obstacle", label: "Obstacle" },
] as const;

const FENETRES = [
  { key: "7j", label: "7 jours" },
  { key: "30j", label: "30 jours" },
  { key: "tout", label: "Depuis le 17/08" },
] as const;

function signe(v: number | null | undefined, d = 4) {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d).replace(".", ",")}`;
}

/** Écart apparié + intervalle, et ce qu'on a le droit d'en dire. */
function EcartLu({ e, mieux }: { e?: Ecart; mieux: string }) {
  if (!e || e.moyenne == null) return <span className="text-muted-foreground">—</span>;
  const ton = !e.conclusif ? "text-muted-foreground" : e.moyenne > 0 ? "text-emerald-700" : "text-red-700";
  return (
    <span className="text-[11px]">
      <span className={`font-semibold tabular-nums ${ton}`}>{signe(e.moyenne)}</span>{" "}
      {e.ic95 && <span className="tabular-nums text-muted-foreground">[{signe(e.ic95[0])} ; {signe(e.ic95[1])}]</span>}
      <span className="block text-muted-foreground">
        {e.conclusif ? (e.moyenne > 0 ? mieux : "moins bien — prouvé") : "non concluant à ce volume"}
      </span>
    </span>
  );
}

const jourCourt = (v: string) => `${v.slice(8)}/${v.slice(5, 7)}`;

export default function PrecisionTab() {
  const [segment, setSegment] = useState<string>("tout");
  const [fenetre, setFenetre] = useState<"7j" | "30j" | "tout">("30j");
  const { data, isLoading } = useSWR<SuiviPayload>(
    ["sup-suivi-precision", segment],
    () => adminApi.supervisionSuiviPrecision(90, segment).then((r) => r.data),
    { refreshInterval: 300_000, keepPreviousData: true },
  );

  if (isLoading && !data) return <Empty>Chargement du suivi de précision…</Empty>;
  if (!data?.mesure_disponible) {
    return <Empty>{data?.pourquoi ?? "Suivi indisponible"} — il est calculé par l&apos;étape nocturne « suivi_precision ».</Empty>;
  }
  const c = data.fenetres?.[fenetre];
  const jours = data.par_jour ?? [];
  const tech = c?.technique;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Segments items={SEGMENTS} actif={segment} onChange={setSegment} />
        <Segments items={FENETRES} actif={fenetre} onChange={(k) => setFenetre(k as "7j" | "30j" | "tout")} />
        <span className="text-[11px] text-muted-foreground">
          Courses du {data.premier_jour?.split("-").reverse().join("/")} au {data.dernier_jour?.split("-").reverse().join("/")}, jugées sur le calcul servi à T-10
        </span>
      </div>

      {c && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="N°1 du classement gagnant"
            hint="Part des courses gagnées par le cheval classé 1er au dernier calcul avant le départ. Référence : le favori du marché (cote la plus basse au même instant), sur les mêmes courses."
            value={c.n1_gagne_servi != null ? pct(c.n1_gagne_servi * 100) : "—"}
            sub={`favori du marché : ${c.favori_gagne_marche != null ? pct(c.favori_gagne_marche * 100) : "—"} · ${num(c.n_courses)} courses`}
            footer={<span className="text-[11px] text-muted-foreground">gagnant dans le top 3 : {c.gagnant_dans_top3_servi != null ? pct(c.gagnant_dans_top3_servi * 100) : "—"}</span>}
          />
          <StatTile
            label="Classement contre le marché"
            hint="AUC intra-course (part des perdants classés sous le gagnant) du classement servi moins celle de la cote, course par course. Positif = l'algorithme ordonne mieux que les parieurs."
            value={c.auc_servi != null ? c.auc_servi.toFixed(4).replace(".", ",") : "—"}
            sub={`marché ${c.auc_marche != null ? c.auc_marche.toFixed(4).replace(".", ",") : "—"}`}
            footer={<EcartLu e={c.classement_vs_marche} mieux="mieux que le marché — prouvé" />}
          />
          <StatTile
            label="Justesse des cotes justes"
            hint="Log-vraisemblance du gagnant : la probabilité (1/cote juste) que l'algorithme donnait au cheval qui a gagné, comparée à celle de la cote. Positif = cotes justes plus justes que la cote PMU."
            value={signe(c.cote_juste_vs_marche.moyenne)}
            sub="écart par course avec la cote PMU"
            footer={<EcartLu e={c.cote_juste_vs_marche} mieux="plus justes que la cote — prouvé" />}
          />
          <StatTile
            label="Modèle technique (observation)"
            hint="Le modèle qui n'utilise AUCUNE information de marché, mélangé à la cote, mesuré sur les mêmes courses — uniquement celles postérieures à son entraînement, avec le modèle en place le jour mesuré. Positif = il ferait mieux que ce qui est servi."
            value={tech?.n_courses ? signe(tech.cote_juste_vs_servi.moyenne) : "—"}
            sub={tech?.n_courses ? `cotes justes vs servi · n°1 gagnant ${tech.n1_gagne != null ? pct(tech.n1_gagne * 100) : "—"}` : "pas encore mesuré"}
            footer={tech?.n_courses ? <EcartLu e={tech.classement_vs_servi} mieux="classe mieux que le servi — prouvé" /> : null}
          />
        </div>
      )}

      {jours.length > 1 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Section
            title="N°1 gagnant, sur 7 jours glissants"
            desc="Classement servi contre favori du marché et modèle technique, mêmes courses. Une journée pèse selon son nombre de courses."
          >
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={jours} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="jour" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} tickFormatter={jourCourt} />
                <YAxis domain={[0.2, 0.4]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={46} tickFormatter={(v) => `${Math.round(v * 100)} %`} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => pct(v * 100)} labelFormatter={(l) => jourCourt(String(l))} />} />
                <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                <Line type="monotone" dataKey="n1_gagne_7j" name="Classement servi" stroke="#F59E0B" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="favori_gagne_7j" name="Favori du marché" stroke="#64748B" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="n1_gagne_technique_7j" name="Modèle technique" stroke="#059669" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Section>
          <Section
            title="Justesse des cotes justes, sur 7 jours glissants"
            desc="Au-dessus de zéro = plus juste que la référence. Servi contre la cote PMU, et modèle technique contre le servi."
          >
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={jours} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="jour" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={24} tickFormatter={jourCourt} />
                <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={52} tickFormatter={(v) => v.toFixed(2).replace(".", ",")} />
                <ReferenceLine y={0} stroke="#94A3B8" />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => signe(v)} labelFormatter={(l) => jourCourt(String(l))} />} />
                <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                <Line type="monotone" dataKey="cote_juste_vs_marche_7j" name="Servi vs cote PMU" stroke="#F59E0B" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="technique_vs_servi_7j" name="Technique vs servi" stroke="#059669" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Section>
        </div>
      )}

      {c && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Section
            title="Les cotes justes tiennent-elles leurs promesses ?"
            desc="Tous les partants de la fenêtre, rangés par cote juste servie : probabilité annoncée contre fréquence de victoire réellement observée."
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[12px]">
                <thead>
                  <tr className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 pr-3">Cote juste</th>
                    <th className="py-1.5 pr-3 text-right">Partants</th>
                    <th className="py-1.5 pr-3 text-right">Annoncé</th>
                    <th className="py-1.5 pr-3 text-right">Réalisé</th>
                    <th className="py-1.5 text-right">Victoires</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {c.calibration_cote_juste.map((t) => (
                    <tr key={t.tranche} className="border-t border-border/60">
                      <td className="py-1.5 pr-3 font-medium">{t.tranche}</td>
                      <td className="py-1.5 pr-3 text-right">{num(t.partants)}</td>
                      <td className="py-1.5 pr-3 text-right">{pct(t.annonce * 100)}</td>
                      <td className="py-1.5 pr-3 text-right">{pct(t.realise * 100)}</td>
                      <td className="py-1.5 text-right">{num(t.victoires)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Note>Placement : log-loss du placé servi {c.placement_logloss_servi != null ? c.placement_logloss_servi.toFixed(4).replace(".", ",") : "—"}{tech?.placement_logloss != null ? `, modèle technique ${tech.placement_logloss.toFixed(4).replace(".", ",")}` : ""} (plus bas = plus juste) · top 3 annoncé juste à {c.top3_annonce_juste_servi != null ? pct(c.top3_annonce_juste_servi * 100) : "—"}.</Note>
          </Section>
          <Section
            title="Valeurs détectées, réglées au rapport PMU"
            desc="Paris de valeur de la fenêtre par niveau, 1 € au Simple Gagnant sur le rapport officiel. Gains plafonnés à ×30 dans la colonne winsorisée. Le n°1 du classement joué pareil sert de référence."
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[12px]">
                <thead>
                  <tr className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 pr-3">Niveau</th>
                    <th className="py-1.5 pr-3 text-right">Paris</th>
                    <th className="py-1.5 pr-3 text-right">Gagnants</th>
                    <th className="py-1.5 pr-3 text-right">ROI</th>
                    <th className="py-1.5 text-right">ROI ×30</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {c.valeurs_detectees.map((v) => (
                    <tr key={v.niveau} className="border-t border-border/60">
                      <td className="py-1.5 pr-3 font-medium">{"★".repeat(v.niveau)}</td>
                      <td className="py-1.5 pr-3 text-right">{num(v.paris)}</td>
                      <td className="py-1.5 pr-3 text-right">{num(v.gagnants)}</td>
                      <td className={`py-1.5 pr-3 text-right ${v.roi >= 0 ? "text-emerald-700" : "text-red-700"}`}>{signe(v.roi * 100, 1)} %</td>
                      <td className="py-1.5 text-right">{signe(v.roi_winsorise * 100, 1)} %</td>
                    </tr>
                  ))}
                  {c.simple_gagnant_n1 && (
                    <tr className="border-t border-border">
                      <td className="py-1.5 pr-3 text-muted-foreground">N°1 du classement</td>
                      <td className="py-1.5 pr-3 text-right">{num(c.simple_gagnant_n1.paris)}</td>
                      <td className="py-1.5 pr-3 text-right">—</td>
                      <td className="py-1.5 pr-3 text-right">{signe(c.simple_gagnant_n1.roi * 100, 1)} %</td>
                      <td className="py-1.5 text-right">{signe(c.simple_gagnant_n1.roi_winsorise * 100, 1)} %</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <Note>Un ROI sur quelques centaines de paris a une erreur-type de 10 à 20 points : lire la tendance sur 30 jours, jamais sur une journée.</Note>
          </Section>
        </div>
      )}
    </div>
  );
}
