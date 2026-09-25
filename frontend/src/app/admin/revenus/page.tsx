"use client";

/**
 * Revenus — l'argent réellement encaissé, mois par mois, et ce qui va tomber.
 *
 * Demande de l'exploitant (2026-09-25) : « un visuel sur les revenus par mois
 * avec le détail, et la date de renouvellement prévue des abonnés payants »,
 * puis « des graphs avec des courbes, beaux, détaillés, précis, sobres et pro ».
 *
 * Deux natures de chiffres, jamais mélangées :
 *   · ENCAISSÉ — la somme des `paiement_recu` du journal, écrits à chaque
 *     facture Stripe payée. C'est de l'argent constaté : trait plein.
 *   · PRÉVU — l'échéancier lu sur la fin de période (ou d'essai) de chaque
 *     abonnement vivant. Une résiliation programmée ou un impayé n'y comptent
 *     pour rien. Toujours en POINTILLÉS, toujours nommé « prévu ».
 */

import { useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CalendarClock, ChevronLeft, ChevronRight, Euro, Landmark, Repeat } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, CelluleCompte, DefilementX, EnTetePage, Etat, GrilleKpi, Kpi, Panneau, Puce,
  Segments, Squelette, TD, TH, Tableau, Vide, eur, num, pct, signedPct, type Colonne,
} from "@/components/admin/ui";
import { useAbonnements, useRevenus } from "@/components/admin/data";
import {
  AXE, Anneau, COULEUR_FORMULE, Fraicheur, Infobulle, Legende, PALETTE, useRecuLe,
} from "@/components/admin/graphes";
import type { Echeance, MoisRevenu, PaiementRecu } from "@/components/admin/types";
import CompteARebours from "@/components/admin/vues/CompteARebours";

/* ─────────────────────────────── formats ───────────────────────────────── */

const euros = (cents: number | null | undefined, digits = 0) =>
  cents == null ? "—" : eur(cents / 100, digits);
const eurosFin = (cents: number) => eur(cents / 100, cents % 100 ? 2 : 0);
const eurAxe = (v: number) => (Math.abs(v) >= 1000 ? `${(v / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k€` : `${Math.round(v)} €`);

const majuscule = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

function nomMois(cle: string, forme: "court" | "long" | "abrege" = "court") {
  const [a, m] = cle.split("-").map(Number);
  const d = new Date(a, m - 1, 1);
  if (forme === "long") return majuscule(d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" }));
  if (forme === "abrege") return d.toLocaleDateString("fr-FR", { month: "short" }).replace(".", "");
  return d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" }).replace(".", "");
}

const dateCourte = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }) : "—";

const variation = (a: number, b: number | null | undefined) =>
  b != null && b > 0 ? ((a - b) / b) * 100 : null;

const NATURE_ECHEANCE: Record<Echeance["nature"], { label: string; ton: "ok" | "attention" | "alerte" | "neutre" }> = {
  renouvellement: { label: "Renouvellement", ton: "ok" },
  premier_prelevement: { label: "1er prélèvement (fin d'essai)", ton: "attention" },
  fin_acces: { label: "Résilié — fin d'accès", ton: "neutre" },
  impaye: { label: "Impayé — relances en cours", ton: "alerte" },
};

/* ─────────────────────────── courbe principale ─────────────────────────── */

interface Point {
  cle: string;
  label: string;
  encaisse: number | null;
  prevu: number | null;
  cumul: number | null;
  cumulPrevu: number | null;
  m?: MoisRevenu;
  precedent?: MoisRevenu;
}

type Vue = "mensuel" | "cumul";

function CourbeRevenus({
  points, vue, selection, onSelection, moyenne,
}: {
  points: Point[];
  vue: Vue;
  selection: string | null;
  onSelection: (cle: string) => void;
  moyenne: number;
}) {
  const cleReel = vue === "mensuel" ? "encaisse" : "cumul";
  const clePrevu = vue === "mensuel" ? "prevu" : "cumulPrevu";
  const choisi = points.find((p) => p.cle === selection);
  const yChoisi = choisi ? (choisi[cleReel] as number | null) : null;

  return (
    <div className="h-[320px] w-full sm:h-[360px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={points}
          margin={{ top: 16, right: 12, bottom: 4, left: 0 }}
          onClick={(e: { activePayload?: Array<{ payload: Point }> } | null) => {
            const p = e?.activePayload?.[0]?.payload;
            if (p?.m) onSelection(p.cle);
          }}
          style={{ cursor: "pointer" }}
        >
          <defs>
            <linearGradient id="rev-aire" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={PALETTE.ardoise} stopOpacity={0.16} />
              <stop offset="100%" stopColor={PALETTE.ardoise} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" {...AXE} dy={6} interval="preserveStartEnd" minTickGap={12} />
          <YAxis {...AXE} width={52} tickFormatter={eurAxe} domain={[0, (max: number) => Math.max(10, Math.ceil((max * 1.12) / 10) * 10)]} />
          <Tooltip
            cursor={{ stroke: PALETTE.gris, strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as Point | undefined;
              if (!active || !p) return null;
              if (!p.m) {
                return (
                  <Infobulle
                    titre={<span>{nomMois(p.cle, "long")} · prévision</span>}
                    lignes={[{
                      label: vue === "mensuel" ? "Prélèvements prévus" : "Cumul prévu",
                      valeur: eur((vue === "mensuel" ? p.prevu : p.cumulPrevu) ?? 0, 2),
                      couleur: PALETTE.ardoiseMoyen, pointille: true,
                    }]}
                    pied="D'après l'échéancier des abonnements actifs"
                  />
                );
              }
              const v = variation(p.m.encaisse_cents, p.precedent?.encaisse_cents);
              return (
                <Infobulle
                  titre={<span>{nomMois(p.cle, "long")}</span>}
                  lignes={[
                    { label: "Encaissé", valeur: euros(p.m.encaisse_cents, 2), couleur: PALETTE.ardoise },
                    { label: "Nouveaux clients", valeur: euros(p.m.nouveaux_cents, 2), secondaire: true },
                    { label: "Renouvellements", valeur: euros(p.m.renouvellements_cents, 2), secondaire: true },
                    ...(p.prevu != null ? [{ label: "Atterrissage prévu", valeur: eur(p.prevu, 2), couleur: PALETTE.ardoiseMoyen, pointille: true }] : []),
                    ...(vue === "cumul" ? [{ label: "Cumul", valeur: eur(p.cumul ?? 0, 2) }] : []),
                  ]}
                  pied={
                    <span className="flex justify-between gap-4">
                      <span>{num(p.m.nb_paiements)} paiement{p.m.nb_paiements > 1 ? "s" : ""} · {num(p.m.nb_clients)} client{p.m.nb_clients > 1 ? "s" : ""}</span>
                      {v != null && (
                        <span className={cn("font-semibold", v >= 0 ? "text-emerald-700" : "text-red-700")}>{signedPct(v)}</span>
                      )}
                    </span>
                  }
                />
              );
            }}
          />
          {vue === "mensuel" && moyenne > 0 && (
            <ReferenceLine
              y={moyenne} stroke={PALETTE.gris} strokeDasharray="4 4"
              label={{ value: `Moyenne ${eur(moyenne)}`, position: "insideTopLeft", fontSize: 11, fill: PALETTE.axe, dy: -4 }}
            />
          )}
          {choisi && (
            <ReferenceLine x={choisi.label} stroke={PALETTE.or} strokeOpacity={0.55} />
          )}
          <Area
            type="monotone" dataKey={cleReel} name="Encaissé"
            stroke={PALETTE.ardoise} strokeWidth={2} fill="url(#rev-aire)"
            dot={{ r: 3, fill: "#fff", stroke: PALETTE.ardoise, strokeWidth: 1.5 }}
            activeDot={{ r: 5, fill: PALETTE.ardoise, stroke: "#fff", strokeWidth: 2 }}
            connectNulls={false} isAnimationActive animationDuration={600}
          />
          <Line
            type="monotone" dataKey={clePrevu} name="Prévu"
            stroke={PALETTE.ardoiseMoyen} strokeWidth={1.75} strokeDasharray="5 4"
            dot={{ r: 3, fill: "#fff", stroke: PALETTE.ardoiseMoyen, strokeWidth: 1.5 }}
            activeDot={{ r: 4.5 }} connectNulls isAnimationActive={false}
          />
          {choisi && yChoisi != null && (
            <ReferenceDot x={choisi.label} y={yChoisi} r={5.5} fill={PALETTE.or} stroke="#fff" strokeWidth={2} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Bandeau de lecture sous la courbe : les repères qu'on cherche des yeux. */
function Reperes({ mois }: { mois: MoisRevenu[] }) {
  const actifs = mois.filter((m) => m.encaisse_cents > 0);
  if (actifs.length === 0) return null;
  const meilleur = actifs.reduce((a, b) => (b.encaisse_cents > a.encaisse_cents ? b : a));
  const faible = actifs.reduce((a, b) => (b.encaisse_cents < a.encaisse_cents ? b : a));
  const premier = actifs[0];
  const dernierComplet = mois.length > 1 ? mois[mois.length - 2] : mois[mois.length - 1];
  const croissance = variation(dernierComplet.encaisse_cents, premier.encaisse_cents);
  const totalNouveaux = mois.reduce((s, m) => s + m.nouveaux_cents, 0);
  const total = mois.reduce((s, m) => s + m.encaisse_cents, 0);
  const cases = [
    { l: "Meilleur mois", v: euros(meilleur.encaisse_cents), d: nomMois(meilleur.mois, "long") },
    { l: "Mois le plus faible", v: euros(faible.encaisse_cents), d: nomMois(faible.mois, "long") },
    {
      l: "Progression",
      v: croissance == null ? "—" : signedPct(croissance, 0),
      d: `${nomMois(premier.mois)} → ${nomMois(dernierComplet.mois)}, dernier mois complet`,
      c: croissance == null ? "" : croissance >= 0 ? "text-emerald-700" : "text-red-700",
    },
    { l: "Part des nouveaux clients", v: total > 0 ? pct((totalNouveaux / total) * 100, 0) : "—", d: `${euros(totalNouveaux)} sur ${euros(total)}` },
  ];
  return (
    <dl className="mt-4 grid grid-cols-2 divide-border border-t border-border pt-4 sm:grid-cols-4 sm:divide-x">
      {cases.map((c, i) => (
        <div key={c.l} className={cn("min-w-0 py-1 sm:px-4", i === 0 && "sm:pl-0")}>
          <dt className="text-xs text-muted-foreground">{c.l}</dt>
          <dd className={cn("mt-0.5 text-base font-semibold tabular-nums text-foreground", c.c)}>{c.v}</dd>
          <dd className="truncate text-xs text-muted-foreground">{c.d}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ───────────────────────── courbes de composition ──────────────────────── */

function CourbeComposition({
  mois, series, empile = false,
}: {
  mois: MoisRevenu[];
  series: Array<{ cle: string; label: string; couleur: string; valeur: (m: MoisRevenu) => number }>;
  empile?: boolean;
}) {
  const data = mois.map((m) => ({
    label: nomMois(m.mois),
    cle: m.mois,
    ...Object.fromEntries(series.map((s) => [s.cle, s.valeur(m) / 100])),
  }));
  return (
    <>
      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {series.map((s) => (
                <linearGradient key={s.cle} id={`cmp-${s.cle}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.couleur} stopOpacity={empile ? 0.28 : 0.14} />
                  <stop offset="100%" stopColor={s.couleur} stopOpacity={empile ? 0.08 : 0.01} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" {...AXE} dy={6} interval="preserveStartEnd" minTickGap={16} />
            <YAxis {...AXE} width={48} tickFormatter={eurAxe} />
            <Tooltip
              cursor={{ stroke: PALETTE.gris, strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as Record<string, number | string> | undefined;
                if (!active || !p) return null;
                const total = series.reduce((s, x) => s + Number(p[x.cle] ?? 0), 0);
                return (
                  <Infobulle
                    titre={<span>{nomMois(String(p.cle), "long")}</span>}
                    lignes={series.map((s) => ({
                      label: s.label,
                      valeur: `${eur(Number(p[s.cle] ?? 0), 2)}${total > 0 ? ` · ${pct((Number(p[s.cle] ?? 0) / total) * 100, 0)}` : ""}`,
                      couleur: s.couleur,
                    }))}
                    pied={<span className="flex justify-between"><span>Total</span><b className="text-foreground">{eur(total, 2)}</b></span>}
                  />
                );
              }}
            />
            {series.map((s) => (
              <Area
                key={s.cle} type="monotone" dataKey={s.cle} name={s.label}
                stackId={empile ? "pile" : undefined}
                stroke={s.couleur} strokeWidth={1.75} fill={empile ? `url(#cmp-${s.cle})` : "none"}
                dot={empile ? false : { r: 2.5, fill: "#fff", stroke: s.couleur, strokeWidth: 1.5 }}
                activeDot={{ r: 4, fill: s.couleur, stroke: "#fff", strokeWidth: 2 }}
                isAnimationActive animationDuration={600}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <Legende className="mt-3" items={series.map((s) => ({ label: s.label, couleur: s.couleur, aire: empile }))} />
    </>
  );
}

/* ─────────────────────────── détail d'un mois ──────────────────────────── */

const COLONNES_PAIEMENTS: Colonne<PaiementRecu>[] = [
  { titre: "Client", rendu: (p) => <CelluleCompte email={p.email ?? "compte supprimé"} />, className: "max-w-[280px]" },
  { titre: "Formule", rendu: (p) => <BadgeFormule plan={p.plan} /> },
  {
    titre: "Nature",
    rendu: (p) => p.nature === "nouveau"
      ? <Etat ton="or">Premier paiement</Etat>
      : <Etat ton="ok">Renouvellement</Etat>,
  },
  {
    titre: "Date",
    rendu: (p) => <span className="whitespace-nowrap text-muted-foreground" title={formatDateTime(p.date)}>{dateCourte(p.date)}</span>,
  },
  { titre: "Montant", rendu: (p) => <span className="font-semibold text-foreground">{eurosFin(p.montant_cents)}</span>, droite: true },
];

function Ecart({ a, b }: { a: number; b: number | null | undefined }) {
  const v = variation(a, b);
  if (v == null) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("font-medium", v >= 0 ? "text-emerald-700" : "text-red-700")}>{signedPct(v, 0)}</span>;
}

function DetailMois({ m, precedent }: { m: MoisRevenu; precedent?: MoisRevenu }) {
  const cases = [
    { label: "Encaissé", v: euros(m.encaisse_cents, 2), a: m.encaisse_cents, b: precedent?.encaisse_cents },
    { label: "Nouveaux clients", v: euros(m.nouveaux_cents, 2), a: m.nouveaux_cents, b: precedent?.nouveaux_cents },
    { label: "Renouvellements", v: euros(m.renouvellements_cents, 2), a: m.renouvellements_cents, b: precedent?.renouvellements_cents },
    { label: "Paiements", v: num(m.nb_paiements), a: m.nb_paiements, b: precedent?.nb_paiements },
    { label: "Panier moyen", v: euros(m.panier_moyen_cents, 2), a: m.panier_moyen_cents ?? 0, b: precedent?.panier_moyen_cents },
    {
      label: "Prélèvements échoués",
      v: m.nb_echecs ? `${m.nb_echecs} · ${euros(m.echecs_cents)}` : "Aucun",
      a: null as number | null, b: null,
    },
  ];
  const total = m.encaisse_cents;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,17rem)_1fr]">
        <div className="flex items-center gap-5 rounded-lg border border-border bg-muted/40 p-4 lg:flex-col lg:items-stretch">
          <Anneau
            taille={148}
            epaisseur={16}
            className="mx-auto"
            parts={[
              { cle: "standard", label: "Standard", n: m.par_formule.standard, couleur: COULEUR_FORMULE.standard },
              { cle: "expert", label: "Expert", n: m.par_formule.expert, couleur: COULEUR_FORMULE.expert },
            ]}
            centre={
              <>
                <div className="text-[11px] text-muted-foreground">Total</div>
                <div className="text-lg font-semibold tabular-nums">{euros(total)}</div>
              </>
            }
          />
          <dl className="min-w-0 flex-1 space-y-2 text-[13px]">
            {(["standard", "expert"] as const).map((f) => (
              <div key={f} className="flex items-center justify-between gap-3">
                <dt className="flex items-center gap-2 text-muted-foreground">
                  <span className="h-2 w-2 rounded-[3px]" style={{ background: COULEUR_FORMULE[f] }} aria-hidden />
                  {f === "standard" ? "Standard" : "Expert"}
                </dt>
                <dd className="tabular-nums">
                  <b className="font-semibold">{euros(m.par_formule[f])}</b>
                  <span className="ml-1.5 text-xs text-muted-foreground">{total > 0 ? pct((m.par_formule[f] / total) * 100, 0) : "—"}</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3">
          {cases.map((c) => (
            <div key={c.label} className="bg-white p-3.5">
              <dt className="text-xs text-muted-foreground">{c.label}</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{c.v}</dd>
              <dd className="mt-0.5 text-xs text-muted-foreground">
                {c.a != null ? <><Ecart a={c.a} b={c.b} /> vs mois précédent</> : m.nb_echecs ? "accès coupé, relances en cours" : "sur le mois"}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">Paiements du mois</h3>
          <span className="text-xs text-muted-foreground">{num(m.nb_paiements)} factures payées · {euros(m.encaisse_cents, 2)}</span>
        </div>
        <Tableau
          lignes={m.paiements}
          colonnes={COLONNES_PAIEMENTS}
          cle={(p) => `${p.date}-${p.email}-${p.montant_cents}`}
          label={`Paiements de ${nomMois(m.mois, "long")}`}
          vide="Aucun encaissement ce mois-ci."
          limite={10}
        />
      </div>
    </div>
  );
}

/* ─────────────────────────── tableau récapitulatif ─────────────────────── */

function Recapitulatif({ mois, selection, onSelection }: {
  mois: MoisRevenu[]; selection: string | null; onSelection: (c: string) => void;
}) {
  const max = Math.max(1, ...mois.map((m) => m.encaisse_cents));
  const lignes = [...mois].reverse();
  const somme = (f: (m: MoisRevenu) => number) => mois.reduce((s, m) => s + f(m), 0);
  const cellNum = cn(TD, "text-right tabular-nums");
  return (
    <DefilementX label="Revenus mois par mois">
      <table className="w-full min-w-[880px] border-collapse">
        <thead>
          <tr className="border-b border-border bg-muted/50">
            <th className={TH}>Mois</th>
            <th className={cn(TH, "w-[26%]")}>Encaissé</th>
            <th className={cn(TH, "text-right")}>Évol.</th>
            <th className={cn(TH, "text-right")}>Paiements</th>
            <th className={cn(TH, "text-right")}>Nouveaux</th>
            <th className={cn(TH, "text-right")}>Renouv.</th>
            <th className={cn(TH, "text-right")}>Standard</th>
            <th className={cn(TH, "text-right")}>Expert</th>
            <th className={cn(TH, "text-right")}>Échecs</th>
            <th className={cn(TH, "text-right")}>Cumul</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((m, i) => {
            const prec = lignes[i + 1];
            const actif = m.mois === selection;
            return (
              <tr
                key={m.mois}
                onClick={() => onSelection(m.mois)}
                aria-selected={actif}
                className={cn("cursor-pointer border-b border-border/70", actif && "bg-[#faf6ec]")}
              >
                <td className={cn(TD, "whitespace-nowrap font-medium", actif && "shadow-[inset_3px_0_0_0_#a8741a]")}>
                  {nomMois(m.mois, "long")}
                  {i === 0 && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium normal-case text-muted-foreground">en cours</span>}
                </td>
                <td className={TD}>
                  <div className="flex items-center gap-3">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-[#27456b]" style={{ width: `${(m.encaisse_cents / max) * 100}%` }} />
                    </div>
                    <span className="w-20 text-right font-semibold tabular-nums">{euros(m.encaisse_cents)}</span>
                  </div>
                </td>
                <td className={cellNum}><Ecart a={m.encaisse_cents} b={prec?.encaisse_cents} /></td>
                <td className={cellNum}>{num(m.nb_paiements)}</td>
                <td className={cellNum}>{euros(m.nouveaux_cents)}</td>
                <td className={cellNum}>{euros(m.renouvellements_cents)}</td>
                <td className={cellNum}>{euros(m.par_formule.standard)}</td>
                <td className={cellNum}>{euros(m.par_formule.expert)}</td>
                <td className={cn(cellNum, m.nb_echecs ? "text-red-700" : "text-muted-foreground")}>
                  {m.nb_echecs ? `${m.nb_echecs} · ${euros(m.echecs_cents)}` : "—"}
                </td>
                <td className={cn(cellNum, "text-muted-foreground")}>{euros(m.cumul_cents)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border bg-muted/40 font-semibold">
            <td className={TD}>Total</td>
            <td className={cn(TD, "text-right tabular-nums")}>{euros(somme((m) => m.encaisse_cents))}</td>
            <td className={TD} />
            <td className={cellNum}>{num(somme((m) => m.nb_paiements))}</td>
            <td className={cellNum}>{euros(somme((m) => m.nouveaux_cents))}</td>
            <td className={cellNum}>{euros(somme((m) => m.renouvellements_cents))}</td>
            <td className={cellNum}>{euros(somme((m) => m.par_formule.standard))}</td>
            <td className={cellNum}>{euros(somme((m) => m.par_formule.expert))}</td>
            <td className={cellNum}>{num(somme((m) => m.nb_echecs))}</td>
            <td className={TD} />
          </tr>
        </tfoot>
      </table>
    </DefilementX>
  );
}

/* ─────────────────────────────── échéancier ────────────────────────────── */

const COLONNES_ECHEANCES: Colonne<Echeance>[] = [
  { titre: "Abonné", rendu: (e) => <CelluleCompte email={e.email} />, className: "max-w-[280px]" },
  { titre: "Formule", rendu: (e) => <BadgeFormule plan={e.plan} periodicite={e.periodicite} /> },
  { titre: "Prochaine échéance", rendu: (e) => <CompteARebours date={e.date} jours={e.jours_restants} nature={e.nature} /> },
  { titre: "Nature", rendu: (e) => <Etat ton={NATURE_ECHEANCE[e.nature].ton}>{NATURE_ECHEANCE[e.nature].label}</Etat> },
  {
    titre: "Montant prévu",
    rendu: (e) => e.montant_cents > 0
      ? <span className="font-semibold text-foreground">{eurosFin(e.montant_cents)}</span>
      : <span className="text-muted-foreground">0 €</span>,
    droite: true,
  },
];

type FiltreEch = "tous" | "7" | "30" | "resilies";

/** Courbe cumulée de l'argent attendu sur les 30 prochains jours. */
function CourbeAttendu({ echeances }: { echeances: Echeance[] }) {
  const data = useMemo(() => {
    let cumul = 0;
    return Array.from({ length: 31 }, (_, i) => {
      const jour = echeances.filter((e) => e.jours_restants != null && e.montant_cents > 0 && Math.max(0, Math.floor(e.jours_restants)) === i);
      const montant = jour.reduce((s, e) => s + e.montant_cents, 0) / 100;
      cumul += montant;
      const d = new Date(Date.now() + i * 86_400_000);
      return {
        i, montant, cumul, n: jour.length,
        label: i === 0 ? "Auj." : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" }).replace(".", ""),
        date: d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }),
        noms: jour.map((e) => e.email),
      };
    });
  }, [echeances]);
  return (
    <div className="h-[200px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="att-aire" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={PALETTE.vert} stopOpacity={0.16} />
              <stop offset="100%" stopColor={PALETTE.vert} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" {...AXE} dy={6} interval={4} />
          <YAxis {...AXE} width={48} tickFormatter={eurAxe} />
          <Tooltip
            cursor={{ stroke: PALETTE.gris, strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
              if (!active || !p) return null;
              return (
                <Infobulle
                  titre={majuscule(p.date)}
                  lignes={[
                    { label: "Attendu ce jour", valeur: eur(p.montant, 2), couleur: PALETTE.vert },
                    { label: "Cumul depuis aujourd'hui", valeur: eur(p.cumul, 2) },
                  ]}
                  pied={p.n > 0 ? `${p.n} prélèvement${p.n > 1 ? "s" : ""} : ${p.noms.slice(0, 3).join(", ")}${p.n > 3 ? "…" : ""}` : "Aucun prélèvement ce jour"}
                />
              );
            }}
          />
          <Area
            type="monotone" dataKey="cumul" name="Cumul attendu"
            stroke={PALETTE.vert} strokeWidth={2} fill="url(#att-aire)"
            dot={(props: { cx?: number; cy?: number; payload?: { n: number }; index?: number }) =>
              props.payload && props.payload.n > 0 && props.cx != null && props.cy != null
                ? <circle key={props.index} cx={props.cx} cy={props.cy} r={3} fill="#fff" stroke={PALETTE.vert} strokeWidth={1.5} />
                : <g key={props.index} />}
            activeDot={{ r: 4.5, fill: PALETTE.vert, stroke: "#fff", strokeWidth: 2 }}
            isAnimationActive animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Echeancier({ echeances }: { echeances: Echeance[] }) {
  const [filtre, setFiltre] = useState<FiltreEch>("30");
  const dans = (e: Echeance, j: number) => e.jours_restants != null && e.jours_restants <= j;
  const somme = (l: Echeance[]) => l.reduce((s, e) => s + e.montant_cents, 0);
  const sous7 = echeances.filter((e) => dans(e, 7) && e.montant_cents > 0);
  const sous30 = echeances.filter((e) => dans(e, 30) && e.montant_cents > 0);
  const resilies = echeances.filter((e) => e.nature === "fin_acces");
  const essais = echeances.filter((e) => e.nature === "premier_prelevement");

  const lignes = filtre === "7" ? echeances.filter((e) => dans(e, 7))
    : filtre === "30" ? echeances.filter((e) => dans(e, 30))
    : filtre === "resilies" ? resilies
    : echeances;

  const cases = [
    { l: "Attendu sous 7 jours", v: euros(somme(sous7)), d: `${sous7.length} prélèvement${sous7.length > 1 ? "s" : ""}` },
    { l: "Attendu sous 30 jours", v: euros(somme(sous30)), d: `${sous30.length} prélèvement${sous30.length > 1 ? "s" : ""}` },
    { l: "Fins d'essai à venir", v: num(essais.length), d: `${euros(somme(essais))} si tous convertissent` },
    { l: "Résiliations programmées", v: num(resilies.length), d: "ne seront plus débités" },
  ];

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border lg:grid-cols-4">
        {cases.map((c) => (
          <div key={c.l} className="bg-white p-3.5">
            <dt className="text-xs text-muted-foreground">{c.l}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums">{c.v}</dd>
            <dd className="text-xs text-muted-foreground">{c.d}</dd>
          </div>
        ))}
      </dl>

      <div>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">Encaissements attendus sur 30 jours</h3>
          <Legende items={[{ label: "Cumul attendu (prévision)", couleur: PALETTE.vert }]} />
        </div>
        <CourbeAttendu echeances={echeances} />
      </div>

      <div className="space-y-3">
        <Segments
          items={[
            { key: "7", label: `7 jours · ${echeances.filter((e) => dans(e, 7)).length}` },
            { key: "30", label: `30 jours · ${echeances.filter((e) => dans(e, 30)).length}` },
            { key: "tous", label: `Tous · ${echeances.length}` },
            { key: "resilies", label: `Résiliés · ${resilies.length}` },
          ] as const}
          actif={filtre}
          onChange={setFiltre}
          taille="compact"
          className="w-fit max-w-full"
        />
        <Tableau
          lignes={lignes}
          colonnes={COLONNES_ECHEANCES}
          cle={(e) => e.stripe_subscription_id ?? e.user_id}
          label="Échéancier des prélèvements"
          vide="Aucune échéance sur cette période."
          limite={15}
        />
      </div>
    </div>
  );
}

/* ───────────────────────────────── page ────────────────────────────────── */

export default function RevenusPage() {
  const [fenetre, setFenetre] = useState<"6" | "12" | "24">("12");
  const [vue, setVue] = useState<Vue>("mensuel");
  const { data } = useRevenus(Number(fenetre));
  const { data: abos } = useAbonnements();
  const recu = useRecuLe(data);
  const [choix, setChoix] = useState<string | null>(null);

  const points = useMemo<Point[]>(() => {
    if (!data) return [];
    const courant = data.mois[data.mois.length - 1]?.mois;
    const passes: Point[] = data.mois.map((m, i) => ({
      cle: m.mois,
      label: nomMois(m.mois),
      encaisse: m.encaisse_cents / 100,
      // Le prévu part du mois en cours (son atterrissage) pour prolonger la courbe.
      prevu: m.mois === courant ? data.totaux.atterrissage_mois_cents / 100 : null,
      cumul: m.cumul_cents / 100,
      cumulPrevu: m.mois === courant ? (m.cumul_cents + data.totaux.reste_a_encaisser_mois_cents) / 100 : null,
      m,
      precedent: data.mois[i - 1],
    }));
    let cumulPrevu = passes[passes.length - 1]?.cumulPrevu ?? 0;
    const futurs: Point[] = data.prevision
      .filter((p) => courant && p.mois > courant)
      .slice(0, 3)
      .map((p) => {
        cumulPrevu += p.prevu_cents / 100;
        return { cle: p.mois, label: nomMois(p.mois), encaisse: null, prevu: p.prevu_cents / 100, cumul: null, cumulPrevu };
      });
    return [...passes, ...futurs];
  }, [data]);

  const selection = choix ?? data?.mois[data.mois.length - 1]?.mois ?? null;
  const idx = data?.mois.findIndex((m) => m.mois === selection) ?? -1;
  const moisChoisi = idx >= 0 ? data?.mois[idx] : undefined;
  const t = data?.totaux;
  const serie = data?.mois.map((m) => m.encaisse_cents / 100);
  const progression = t && t.atterrissage_mois_cents > 0 ? (t.mois_courant_cents / t.atterrissage_mois_cents) * 100 : null;

  const choisir = (cle: string) => {
    setChoix(cle);
    document.getElementById("detail-mois")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="space-y-5 sm:space-y-6">
      <EnTetePage
        titre="Revenus"
        icone={<Euro className="h-4 w-4" />}
        desc="Encaissements Stripe réels (factures payées), mois par mois, et échéancier des prochains prélèvements."
        actions={
          <>
            <Fraicheur depuis={recu} cadence={30_000} />
            <Segments
              items={[{ key: "6", label: "6 mois" }, { key: "12", label: "12 mois" }, { key: "24", label: "24 mois" }] as const}
              actif={fenetre}
              onChange={(k) => { setFenetre(k); setChoix(null); }}
              taille="compact"
            />
          </>
        }
      />

      <GrilleKpi>
        <Kpi
          label="Encaissé ce mois"
          nombre={t ? t.mois_courant_cents / 100 : null}
          format={(v) => eur(v)}
          accent="bleu"
          tendance={t?.variation_pct}
          tendanceLabel="vs mois précédent"
          serie={serie}
          sub={t?.mois_precedent_cents != null ? `Mois précédent : ${euros(t.mois_precedent_cents)}` : undefined}
        />
        <Kpi
          label="Atterrissage du mois"
          nombre={t ? t.atterrissage_mois_cents / 100 : null}
          format={(v) => eur(v)}
          icone={<CalendarClock />}
          accent="or"
          sub={t ? (
            <>
              <div className="mb-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-[#27456b]" style={{ width: `${Math.min(100, progression ?? 0)}%` }} />
              </div>
              {progression != null ? `${pct(progression, 0)} déjà encaissé · ` : ""}{euros(t.reste_a_encaisser_mois_cents)} restant à prélever
            </>
          ) : undefined}
        />
        <Kpi
          label="Revenu récurrent mensuel"
          nombre={abos?.resume.mrr ?? null}
          format={(v) => eur(v)}
          icone={<Repeat />}
          accent="ok"
          sub={abos ? `${eur(abos.resume.arr)} par an · ${abos.resume.abonnes_payants} abonnés payants` : undefined}
        />
        <Kpi
          label={`Total sur ${fenetre} mois`}
          nombre={t ? t.periode_cents / 100 : null}
          format={(v) => eur(v)}
          icone={<Landmark />}
          accent="violet"
          sub={t ? `Moyenne ${euros(t.moyenne_mensuelle_cents)} / mois · ${num(t.nb_paiements)} paiements` : undefined}
        />
      </GrilleKpi>

      <Panneau
        titre="Évolution des encaissements"
        desc="Trait plein : argent encaissé. Pointillés : prélèvements prévus par l'échéancier. Cliquez un point pour afficher le détail du mois."
        actions={
          <Segments
            items={[{ key: "mensuel", label: "Par mois" }, { key: "cumul", label: "Cumulé" }] as const}
            actif={vue}
            onChange={setVue}
            taille="compact"
          />
        }
      >
        {!data ? <Squelette lignes={8} /> : data.mois.every((m) => m.encaisse_cents === 0) && data.prevision.length === 0
          ? <Vide>Aucun encaissement enregistré sur la période.</Vide>
          : (
            <>
              <Legende
                className="mb-2"
                items={[
                  { label: vue === "mensuel" ? "Encaissé" : "Encaissé cumulé", couleur: PALETTE.ardoise },
                  { label: "Prévu", couleur: PALETTE.ardoiseMoyen, pointille: true },
                  ...(vue === "mensuel" ? [{ label: "Moyenne de la période", couleur: PALETTE.gris, pointille: true }] : []),
                  { label: "Mois sélectionné", couleur: PALETTE.or },
                ]}
              />
              <CourbeRevenus
                points={points}
                vue={vue}
                selection={selection}
                onSelection={choisir}
                moyenne={t ? t.moyenne_mensuelle_cents / 100 : 0}
              />
              <Reperes mois={data.mois} />
            </>
          )}
      </Panneau>

      {data && (
        <div className="grid gap-5 xl:grid-cols-2 xl:gap-6">
          <Panneau titre="Nouveaux clients et renouvellements" desc="Premiers paiements et échéances suivantes, empilés : le haut de la courbe est le total encaissé.">
            <CourbeComposition
              mois={data.mois}
              empile
              series={[
                { cle: "renouvellements", label: "Renouvellements", couleur: PALETTE.ardoise, valeur: (m) => m.renouvellements_cents },
                { cle: "nouveaux", label: "Nouveaux clients", couleur: PALETTE.or, valeur: (m) => m.nouveaux_cents },
              ]}
            />
          </Panneau>
          <Panneau titre="Par formule" desc="Encaissements Standard et Expert, mois par mois.">
            <CourbeComposition
              mois={data.mois}
              series={[
                { cle: "standard", label: "Standard", couleur: COULEUR_FORMULE.standard, valeur: (m) => m.par_formule.standard },
                { cle: "expert", label: "Expert", couleur: COULEUR_FORMULE.expert, valeur: (m) => m.par_formule.expert },
              ]}
            />
          </Panneau>
        </div>
      )}

      {moisChoisi && data && (
        <div id="detail-mois" className="scroll-mt-20">
          <Panneau
            titre={`Détail du mois · ${nomMois(moisChoisi.mois, "long")}`}
            desc="Chaque ligne est une facture Stripe payée, au centime près."
            actions={
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label="Mois précédent"
                  disabled={idx <= 0}
                  onClick={() => setChoix(data.mois[idx - 1].mois)}
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-white text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <Puce>{euros(moisChoisi.encaisse_cents, 2)}</Puce>
                <button
                  type="button"
                  aria-label="Mois suivant"
                  disabled={idx >= data.mois.length - 1}
                  onClick={() => setChoix(data.mois[idx + 1].mois)}
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-white text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            }
          >
            <DetailMois m={moisChoisi} precedent={data.mois[idx - 1]} />
          </Panneau>
        </div>
      )}

      <Panneau
        titre="Échéancier des abonnés"
        desc="Date et montant du prochain prélèvement de chaque abonnement actif. Un abonnement résilié ne sera plus débité."
        actions={data ? <Puce>{data.echeancier.length} abonnements</Puce> : undefined}
      >
        {!data ? <Squelette lignes={6} /> : <Echeancier echeances={data.echeancier} />}
      </Panneau>

      <Panneau
        titre="Tableau mois par mois"
        desc="Cliquez une ligne pour afficher le détail du mois."
        bodyClassName="p-0 sm:p-0"
      >
        {!data ? <div className="p-5"><Squelette lignes={6} /></div>
          : <div className="px-4 py-4 sm:px-5"><Recapitulatif mois={data.mois} selection={selection} onSelection={choisir} /></div>}
      </Panneau>
    </div>
  );
}
