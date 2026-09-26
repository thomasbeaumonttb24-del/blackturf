"use client";

/**
 * Relevé des encaissements — le visuel qui sert aux déclarations de revenus.
 *
 * Demande de l'exploitant (2026-09-25) : « un vrai visuel par mois encaissé qui
 * me sert pour mes déclarations ». D'où trois partis pris :
 *
 *   · des BARRES étiquetées (un montant par période, lisible sans survol) —
 *     la courbe raconte une tendance, la déclaration a besoin d'un chiffre ;
 *   · des périodes CIVILES au choix (mois, trimestre, année), sur une année
 *     civile sélectionnée, parce que c'est ainsi qu'on déclare ;
 *   · un tableau qui distingue ce qui a été encaissé (brut), rendu
 *     (remboursements), acquis (chiffre d'affaires encaissé), prélevé par
 *     Stripe (frais), réellement crédité (net) et viré sur le compte bancaire.
 *
 * Les chiffres viennent de l'API Stripe quand elle répond (cf. `source`) ; le
 * bandeau le dit. L'export CSV reprend exactement ce qui est affiché, au format
 * attendu par un tableur français (point-virgule, virgule décimale, UTF-8).
 */

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { DefilementX, Segments, TD, TH, Vide, eur, num } from "../ui";
import { AXE, Infobulle, PALETTE } from "../graphes";
import type { MoisRevenu, RevenusData } from "../types";

type Grain = "mois" | "trimestre" | "annee";

interface Periode {
  cle: string;
  label: string;
  labelLong: string;
  mois: MoisRevenu[];
  brut: number;
  rembourse: number;
  ca: number;
  frais: number;
  net: number;
  verse: number;
  paiements: number;
  enCours: boolean;
}

const MOIS_LONGS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const MOIS_COURTS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"];
const maj = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
const c2e = (c: number) => c / 100;
const euros = (c: number) => eur(c / 100, c % 100 ? 2 : 0);
/** Une déduction : « −0,97 € », ou « — » quand il n'y a rien à déduire. */
const moins = (c: number) => (c ? `−${euros(c)}` : "—");
/** Montant pour tableur français : virgule décimale, sans symbole. */
const csvMontant = (c: number | null | undefined) => (c == null ? "" : (c / 100).toFixed(2).replace(".", ","));

function regrouper(mois: MoisRevenu[], annee: number, grain: Grain, courant: string): Periode[] {
  const del = mois.filter((m) => Number(m.mois.slice(0, 4)) === annee);
  const groupes = new Map<string, MoisRevenu[]>();
  for (const m of del) {
    const mm = Number(m.mois.slice(5, 7));
    const cle = grain === "mois" ? m.mois : grain === "trimestre" ? `${annee}-T${Math.ceil(mm / 3)}` : `${annee}`;
    groupes.set(cle, [...(groupes.get(cle) ?? []), m]);
  }
  return [...groupes.entries()].map(([cle, ms]) => {
    const s = (f: (x: MoisRevenu) => number) => ms.reduce((a, x) => a + f(x), 0);
    const mm = Number(cle.slice(5, 7));
    const label = grain === "mois" ? MOIS_COURTS[mm - 1] : grain === "trimestre" ? cle.slice(5) : cle;
    const labelLong = grain === "mois" ? `${maj(MOIS_LONGS[mm - 1])} ${annee}`
      : grain === "trimestre" ? `${cle.slice(5)} ${annee} (${MOIS_COURTS[(Number(cle.slice(6)) - 1) * 3]}.–${MOIS_COURTS[Number(cle.slice(6)) * 3 - 1]}.)`
      : `Année ${annee}`;
    return {
      cle, label, labelLong, mois: ms,
      brut: s((x) => x.encaisse_cents),
      rembourse: s((x) => x.rembourse_cents),
      ca: s((x) => x.ca_cents),
      frais: s((x) => x.frais_cents),
      net: s((x) => x.net_cents),
      verse: s((x) => x.verse_cents),
      paiements: s((x) => x.nb_paiements),
      enCours: ms.some((x) => x.mois === courant),
    };
  });
}

function telecharger(nom: string, lignes: string[][]) {
  const contenu = "﻿" + lignes.map((l) => l.map((c) => (/[;"\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([contenu], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nom;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ReleveDeclaration({
  data, onSelectionMois,
}: {
  data: RevenusData;
  onSelectionMois?: (mois: string) => void;
}) {
  const courant = data.mois[data.mois.length - 1]?.mois ?? "";
  const annees = useMemo(
    () => [...new Set(data.mois.map((m) => Number(m.mois.slice(0, 4))))].sort((a, b) => b - a),
    [data.mois],
  );
  const [annee, setAnnee] = useState<number>(annees[0]);
  const [grain, setGrain] = useState<Grain>("mois");
  const anneeEff = annees.includes(annee) ? annee : annees[0];
  const periodes = useMemo(() => regrouper(data.mois, anneeEff, grain, courant), [data.mois, anneeEff, grain, courant]);
  const total = regrouper(data.mois, anneeEff, "annee", courant)[0];
  const fraisConnus = data.source.type === "stripe";
  const premierMoisCouvert = data.mois[0]?.mois;
  const anneeIncomplete = premierMoisCouvert && Number(premierMoisCouvert.slice(0, 4)) === anneeEff && premierMoisCouvert.slice(5) !== "01";

  const exporterResume = () => telecharger(`blackturf-releve-${anneeEff}-${grain}.csv`, [
    ["Période", "Brut encaissé (€)", "Remboursements (€)", "Chiffre d'affaires encaissé (€)", "Frais Stripe (€)", "Net perçu (€)", "Versé en banque (€)", "Nombre de paiements"],
    ...periodes.map((p) => [p.labelLong, csvMontant(p.brut), csvMontant(p.rembourse), csvMontant(p.ca),
      fraisConnus ? csvMontant(p.frais) : "", fraisConnus ? csvMontant(p.net) : "", fraisConnus ? csvMontant(p.verse) : "", String(p.paiements)]),
    ...(total ? [["Total " + anneeEff, csvMontant(total.brut), csvMontant(total.rembourse), csvMontant(total.ca),
      fraisConnus ? csvMontant(total.frais) : "", fraisConnus ? csvMontant(total.net) : "", fraisConnus ? csvMontant(total.verse) : "", String(total.paiements)]] : []),
  ]);

  const exporterDetail = () => telecharger(`blackturf-paiements-${anneeEff}.csv`, [
    ["Date (Paris)", "Client", "Formule", "Montant encaissé (€)", "Dont remboursé (€)", "Frais Stripe (€)", "Net perçu (€)", "Nature", "Référence Stripe", "Reçu"],
    ...(total?.mois ?? []).flatMap((m) => [...m.paiements].reverse()).map((p) => [
      new Date(p.date).toLocaleString("fr-FR", { timeZone: "Europe/Paris" }),
      p.email ?? "", p.plan === "expert" ? "Expert" : "Standard",
      csvMontant(p.montant_cents), csvMontant(p.rembourse_cents), csvMontant(p.frais_cents), csvMontant(p.net_cents),
      p.nature === "nouveau" ? "Premier paiement" : "Renouvellement", p.charge_id ?? p.facture_id ?? "", p.recu_url ?? "",
    ]),
  ]);

  const graphe = periodes.map((p) => ({ ...p, valeur: c2e(p.ca) }));
  const cell = cn(TD, "text-right tabular-nums");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Segments
            items={annees.map((a) => ({ key: String(a), label: String(a) }))}
            actif={String(anneeEff)}
            onChange={(k) => setAnnee(Number(k))}
            taille="compact"
          />
          <Segments
            items={[{ key: "mois", label: "Par mois" }, { key: "trimestre", label: "Par trimestre" }, { key: "annee", label: "Année" }] as const}
            actif={grain}
            onChange={setGrain}
            taille="compact"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={exporterResume}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-medium text-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)] hover:bg-muted/60">
            <Download className="h-3.5 w-3.5" /> Relevé {grain === "mois" ? "mensuel" : grain === "trimestre" ? "trimestriel" : "annuel"} (CSV)
          </button>
          <button type="button" onClick={exporterDetail}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-medium text-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)] hover:bg-muted/60">
            <Download className="h-3.5 w-3.5" /> Détail des paiements {anneeEff} (CSV)
          </button>
        </div>
      </div>

      {total && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-6">
          {[
            { l: `Chiffre d'affaires encaissé ${anneeEff}`, v: euros(total.ca), fort: true },
            { l: "Brut encaissé", v: euros(total.brut) },
            { l: "Remboursements", v: total.rembourse ? `−${euros(total.rembourse)}` : "0 €" },
            { l: "Frais Stripe", v: fraisConnus ? moins(total.frais) : "—" },
            { l: "Net perçu", v: fraisConnus ? euros(total.net) : "—" },
            { l: "Versé en banque", v: fraisConnus ? euros(total.verse) : "—" },
          ].map((c) => (
            <div key={c.l} className={cn("bg-white p-3.5", c.fort && "bg-[#f6f8fb]")}>
              <dt className="text-xs text-muted-foreground">{c.l}</dt>
              <dd className={cn("mt-1 tabular-nums", c.fort ? "text-xl font-semibold text-[#27456b]" : "text-lg font-semibold")}>{c.v}</dd>
            </div>
          ))}
        </dl>
      )}

      {periodes.every((p) => p.brut === 0) ? (
        <Vide>Aucun encaissement en {anneeEff}.</Vide>
      ) : (
        <div className="h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={graphe} margin={{ top: 26, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" {...AXE} dy={6} />
              <YAxis {...AXE} width={52} tickFormatter={(v: number) => `${Math.round(v)} €`} />
              <Tooltip
                cursor={{ fill: "rgba(39,69,107,0.05)" }}
                content={({ active, payload }) => {
                  const p = payload?.[0]?.payload as (typeof graphe)[number] | undefined;
                  if (!active || !p) return null;
                  return (
                    <Infobulle
                      titre={p.labelLong + (p.enCours ? " · en cours" : "")}
                      lignes={[
                        { label: "Chiffre d'affaires encaissé", valeur: euros(p.ca), couleur: PALETTE.ardoise },
                        { label: "Brut encaissé", valeur: euros(p.brut), secondaire: true },
                        { label: "Remboursements", valeur: p.rembourse ? `−${euros(p.rembourse)}` : "0 €", secondaire: true },
                        ...(fraisConnus ? [
                          { label: "Frais Stripe", valeur: moins(p.frais), secondaire: true },
                          { label: "Net perçu", valeur: euros(p.net), secondaire: true },
                          { label: "Versé en banque", valeur: euros(p.verse), secondaire: true },
                        ] : []),
                      ]}
                      pied={`${num(p.paiements)} paiement${p.paiements > 1 ? "s" : ""}`}
                    />
                  );
                }}
              />
              <Bar
                dataKey="valeur" name="Chiffre d'affaires encaissé" radius={[4, 4, 0, 0]} maxBarSize={56}
                fill={PALETTE.ardoise}
                onClick={(d: { payload?: Periode }) => {
                  const p = d?.payload;
                  if (grain === "mois" && p && onSelectionMois) onSelectionMois(p.cle);
                }}
                style={{ cursor: grain === "mois" && onSelectionMois ? "pointer" : "default" }}
              >
                <LabelList
                  dataKey="valeur" position="top" offset={8}
                  formatter={(v: number) => (v ? eur(v, v % 1 ? 2 : 0) : "")}
                  style={{ fontSize: 11, fontWeight: 600, fill: PALETTE.encre }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <DefilementX label={`Relevé des encaissements ${anneeEff}`}>
        <table className="w-full min-w-[820px] border-collapse">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              <th className={TH}>Période</th>
              <th className={cn(TH, "text-right")}>Brut encaissé</th>
              <th className={cn(TH, "text-right")}>Remboursements</th>
              <th className={cn(TH, "text-right text-[#27456b]")}>CA encaissé</th>
              <th className={cn(TH, "text-right")}>Frais Stripe</th>
              <th className={cn(TH, "text-right")}>Net perçu</th>
              <th className={cn(TH, "text-right")}>Versé en banque</th>
              <th className={cn(TH, "text-right")}>Paiements</th>
            </tr>
          </thead>
          <tbody>
            {periodes.map((p) => (
              <tr
                key={p.cle}
                onClick={() => grain === "mois" && onSelectionMois?.(p.cle)}
                className={cn("border-b border-border/70", grain === "mois" && onSelectionMois && "cursor-pointer")}
              >
                <td className={cn(TD, "whitespace-nowrap font-medium")}>
                  {p.labelLong}
                  {p.enCours && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">en cours</span>}
                </td>
                <td className={cell}>{euros(p.brut)}</td>
                <td className={cn(cell, p.rembourse ? "text-red-700" : "text-muted-foreground")}>{p.rembourse ? `−${euros(p.rembourse)}` : "—"}</td>
                <td className={cn(cell, "font-semibold text-[#27456b]")}>{euros(p.ca)}</td>
                <td className={cn(cell, "text-muted-foreground")}>{fraisConnus ? moins(p.frais) : "—"}</td>
                <td className={cell}>{fraisConnus ? euros(p.net) : "—"}</td>
                <td className={cn(cell, "text-muted-foreground")}>{fraisConnus ? euros(p.verse) : "—"}</td>
                <td className={cell}>{num(p.paiements)}</td>
              </tr>
            ))}
          </tbody>
          {total && (
            <tfoot>
              <tr className="border-t-2 border-border bg-muted/40 font-semibold">
                <td className={TD}>Total {anneeEff}{anneeIncomplete ? " (données disponibles)" : ""}</td>
                <td className={cell}>{euros(total.brut)}</td>
                <td className={cell}>{total.rembourse ? `−${euros(total.rembourse)}` : "—"}</td>
                <td className={cn(cell, "text-[#27456b]")}>{euros(total.ca)}</td>
                <td className={cell}>{fraisConnus ? moins(total.frais) : "—"}</td>
                <td className={cell}>{fraisConnus ? euros(total.net) : "—"}</td>
                <td className={cell}>{fraisConnus ? euros(total.verse) : "—"}</td>
                <td className={cell}>{num(total.paiements)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </DefilementX>

      <p className="text-xs leading-relaxed text-muted-foreground">
        <b className="font-medium text-foreground">CA encaissé</b> = sommes effectivement reçues des clients, remboursements
        déduits, montants TTC tels que débités, datés au jour du paiement (heure de Paris).{" "}
        <b className="font-medium text-foreground">Net perçu</b> = après frais Stripe.{" "}
        <b className="font-medium text-foreground">Versé en banque</b> = virements Stripe arrivés sur votre compte ce mois-là
        (décalés de quelques jours).
        {anneeIncomplete && ` La période chargée commence en ${MOIS_LONGS[Number(premierMoisCouvert!.slice(5, 7)) - 1]} ${anneeEff} : les mois antérieurs n'y figurent pas.`}
        {" "}Faites valider le montant à déclarer par votre expert-comptable.
      </p>
    </div>
  );
}
