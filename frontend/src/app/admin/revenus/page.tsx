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
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronLeft, ChevronRight, Euro, FileText, Landmark, Loader2, RefreshCw, Repeat } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, CelluleCompte, EnTetePage, Etat, GrilleKpi, Kpi, Panneau, Puce,
  Segments, Squelette, Tableau, Vide, eur, num, pct, signedPct, type Colonne,
} from "@/components/admin/ui";
import { useAbonnements, useRevenus } from "@/components/admin/data";
import {
  AXE, Anneau, COULEUR_FORMULE, Fraicheur, Infobulle, Legende, PALETTE, useRecuLe,
} from "@/components/admin/graphes";
import type { Echeance, MoisRevenu, PaiementRecu } from "@/components/admin/types";
import CompteARebours from "@/components/admin/vues/CompteARebours";
import ReleveDeclaration from "@/components/admin/vues/ReleveDeclaration";
import { adminApi } from "@/lib/api";

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
                    { label: "Encaissé (CA)", valeur: euros(p.m.ca_cents, 2), couleur: PALETTE.ardoise },
                    ...(p.m.rembourse_cents ? [{ label: "Remboursements", valeur: `−${euros(p.m.rembourse_cents, 2)}`, secondaire: true }] : []),
                    ...(p.m.frais_connus && p.m.nb_paiements > 0 ? [{ label: "Frais Stripe", valeur: `−${euros(p.m.frais_cents, 2)}`, secondaire: true },
                      { label: "Net perçu", valeur: euros(p.m.net_cents, 2), secondaire: true }] : []),
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
            dot={{ r: 3, fill: "#fff", stroke: PALETTE.ardoiseMoyen, strokeWidth: 1.5, strokeDasharray: "0" }}
            activeDot={{ r: 4.5, strokeDasharray: "0" }} connectNulls isAnimationActive={false}
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
  const actifs = mois.filter((m) => m.ca_cents > 0);
  if (actifs.length === 0) return null;
  const meilleur = actifs.reduce((a, b) => (b.ca_cents > a.ca_cents ? b : a));
  const faible = actifs.reduce((a, b) => (b.ca_cents < a.ca_cents ? b : a));
  // Progression : du premier au DERNIER mois complet ayant des encaissements.
  // L'ancienne version comparait au mois précédent même vide, et affichait
  // « −100 % » quand le seul encaissement tombait dans le mois en cours.
  const complets = actifs.filter((m) => m.mois !== mois[mois.length - 1]?.mois);
  const premier = complets[0];
  const dernier = complets[complets.length - 1];
  const croissance = premier && dernier && premier !== dernier ? variation(dernier.ca_cents, premier.ca_cents) : null;
  const totalNouveaux = mois.reduce((s, m) => s + m.nouveaux_cents, 0);
  const total = mois.reduce((s, m) => s + m.encaisse_cents, 0);
  const cases = [
    { l: "Meilleur mois", v: euros(meilleur.ca_cents), d: nomMois(meilleur.mois, "long") },
    { l: "Mois le plus faible", v: euros(faible.ca_cents), d: nomMois(faible.mois, "long") },
    {
      l: "Progression",
      v: croissance == null ? "—" : signedPct(croissance, 0),
      d: croissance == null
        ? "au moins deux mois complets encaissés nécessaires"
        : `${nomMois(premier!.mois)} → ${nomMois(dernier!.mois)} (mois complets)`,
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
  {
    titre: "Montant",
    rendu: (p) => (
      <span className="font-semibold text-foreground">
        {eurosFin(p.montant_cents)}
        {p.rembourse_cents > 0 && <span className="ml-1 text-xs font-normal text-red-700">(−{eurosFin(p.rembourse_cents)} remb.)</span>}
      </span>
    ),
    droite: true,
  },
  { titre: "Frais", rendu: (p) => <span className="text-muted-foreground">{p.frais_cents == null ? "—" : `−${eurosFin(p.frais_cents)}`}</span>, droite: true },
  { titre: "Net", rendu: (p) => <span>{p.net_cents == null ? "—" : eurosFin(p.net_cents)}</span>, droite: true },
  {
    titre: "Reçu",
    rendu: (p) => p.recu_url
      ? <a href={p.recu_url} target="_blank" rel="noopener noreferrer" className="text-xs font-medium text-[#27456b] hover:underline">Reçu Stripe ↗</a>
      : <span className="text-muted-foreground">—</span>,
    droite: true,
  },
];

function Ecart({ a, b }: { a: number; b: number | null | undefined }) {
  const v = variation(a, b);
  if (v == null) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("font-medium", v >= 0 ? "text-emerald-700" : "text-red-700")}>{signedPct(v, 0)}</span>;
}

function DetailMois({ m, precedent }: { m: MoisRevenu; precedent?: MoisRevenu }) {
  const cases = [
    { label: "Encaissé (CA)", v: euros(m.ca_cents, 2), a: m.ca_cents, b: precedent?.ca_cents },
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

/** D'où viennent les chiffres, et ce que le rapprochement a trouvé. */
function BandeauSource({ data }: { data: import("@/components/admin/types").RevenusData }) {
  const [ouvert, setOuvert] = useState(false);
  const manquants = data.rapprochement.absents_du_journal;
  if (data.source.type !== "stripe") {
    return (
      <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <b className="font-semibold">Chiffres provisoires.</b> {data.source.erreur ?? "Stripe indisponible."}{" "}
          Le journal interne peut omettre des paiements : ne vous en servez pas pour une déclaration.
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-white px-4 py-3 text-[13px] shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-700" />
        <span>
          <b className="font-semibold">Source : votre compte Stripe.</b>{" "}
          <span className="text-muted-foreground">
            Débits réussis, remboursements, frais et virements lus directement par l&apos;API
            {data.source.lu_le ? ` · lu à ${new Date(data.source.lu_le).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris" })}` : ""}.
          </span>
        </span>
        {manquants.length > 0 && (
          <button type="button" onClick={() => setOuvert((v) => !v)} className="ml-auto text-xs font-medium text-[#27456b] hover:underline">
            {manquants.length} paiement{manquants.length > 1 ? "s" : ""} absent{manquants.length > 1 ? "s" : ""} du journal interne — {ouvert ? "masquer" : "voir"}
          </button>
        )}
      </div>
      {ouvert && manquants.length > 0 && (
        <div className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
          <p className="mb-2">
            Ces paiements ont bien été encaissés chez Stripe et sont <b className="text-foreground">comptés dans tous les chiffres de cette page</b>.
            Le journal interne du site ne les avait pas enregistrés (anciens webhooks) : cet écart est désormais corrigé pour les prochains paiements.
          </p>
          <ul className="space-y-1">
            {manquants.map((e) => (
              <li key={e.charge_id ?? `${e.date}${e.email}`} className="flex justify-between gap-4 tabular-nums">
                <span>{new Date(e.date).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })} · {e.email ?? "client inconnu"}</span>
                <b className="text-foreground">{euros(e.montant_cents, 2)}</b>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function RevenusPage() {
  const [fenetre, setFenetre] = useState<"6" | "12" | "24">("12");
  const [vue, setVue] = useState<Vue>("mensuel");
  const { data, mutate } = useRevenus(Number(fenetre));
  // Le relevé de déclaration a besoin d'années civiles complètes : 24 mois.
  const { data: data24, mutate: mutate24 } = useRevenus(24);
  const [relecture, setRelecture] = useState(false);
  const { data: abos } = useAbonnements();
  const recu = useRecuLe(data);
  const [choix, setChoix] = useState<string | null>(null);

  const points = useMemo<Point[]>(() => {
    if (!data) return [];
    const courant = data.mois[data.mois.length - 1]?.mois;
    const passes: Point[] = data.mois.map((m, i) => ({
      cle: m.mois,
      label: nomMois(m.mois),
      // Chiffre d'affaires encaissé : débits réussis moins remboursements.
      encaisse: m.ca_cents / 100,
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
  const serie = data?.mois.map((m) => m.ca_cents / 100);
  const progression = t && t.atterrissage_mois_cents > 0 ? (t.mois_courant_cents / t.atterrissage_mois_cents) * 100 : null;

  const choisir = (cle: string) => {
    // Un mois du relevé peut sortir de la fenêtre affichée : on l'élargit.
    if (data && !data.mois.some((m) => m.mois === cle)) setFenetre("24");
    setChoix(cle);
    document.getElementById("detail-mois")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const relireStripe = async () => {
    setRelecture(true);
    try {
      await adminApi.revenus(Number(fenetre), true);
      await Promise.all([mutate(), mutate24()]);
    } finally {
      setRelecture(false);
    }
  };

  return (
    <div className="space-y-5 sm:space-y-6">
      <EnTetePage
        titre="Revenus"
        icone={<Euro className="h-4 w-4" />}
        desc="Encaissements lus directement dans votre compte Stripe, mois par mois, et échéancier des prochains prélèvements."
        actions={
          <>
            <Fraicheur depuis={recu} cadence={30_000} />
            <button
              type="button" onClick={relireStripe} disabled={relecture}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-medium text-muted-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)] hover:text-foreground disabled:opacity-60"
            >
              {relecture ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Relire Stripe
            </button>
            <Segments
              items={[{ key: "6", label: "6 mois" }, { key: "12", label: "12 mois" }, { key: "24", label: "24 mois" }] as const}
              actif={fenetre}
              onChange={(k) => { setFenetre(k); setChoix(null); }}
              taille="compact"
            />
          </>
        }
      />

      {data && <BandeauSource data={data} />}

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

      <Panneau
        titre="Relevé des encaissements pour déclaration"
        desc="Chiffre d'affaires encaissé par mois, trimestre ou année civile, avec remboursements, frais Stripe, net et virements. Exportable en CSV."
        icone={<FileText className="h-3.5 w-3.5" />}
      >
        {!data24 ? <Squelette lignes={8} /> : <ReleveDeclaration data={data24} onSelectionMois={choisir} />}
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
            desc={data.source.type === "stripe"
              ? "Chaque ligne est un paiement réussi lu dans Stripe, au centime près, avec ses frais et son reçu."
              : "Chaque ligne est un paiement du journal interne (Stripe indisponible)."}
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
                <Puce>{euros(moisChoisi.ca_cents, 2)}</Puce>
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


    </div>
  );
}
