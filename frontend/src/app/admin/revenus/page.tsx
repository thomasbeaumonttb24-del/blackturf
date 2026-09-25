"use client";

/**
 * Revenus — l'argent réellement encaissé, mois par mois, et ce qui va tomber.
 *
 * Demande de l'exploitant (2026-09-25) : « un visuel sur les revenus par mois
 * avec le détail, et la date de renouvellement prévue des abonnés payants ».
 *
 * Deux natures de chiffres, jamais mélangées :
 *   · ENCAISSÉ — la somme des `paiement_recu` du journal, écrits à chaque
 *     facture Stripe payée. C'est de l'argent constaté.
 *   · PRÉVU — l'échéancier lu sur la date de fin de période (ou de fin d'essai)
 *     de chaque abonnement vivant. Une résiliation programmée n'y compte pour
 *     rien, un impayé non plus. Ces barres sont hachurées et nommées « prévu ».
 */

import { useMemo, useState } from "react";
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  CalendarClock, CircleDollarSign, Euro, Landmark, Repeat, Sparkles, TrendingUp, UserPlus,
} from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, CelluleCompte, EnTetePage, Etat, GrilleKpi, Kpi, Panneau, Puce, Segments,
  Squelette, TH, TD, DefilementX, Tableau, Vide, eur, num, signedPct, type Colonne,
} from "@/components/admin/ui";
import { useAbonnements, useRevenus } from "@/components/admin/data";
import {
  Anneau3D, Fraicheur, InfobulleVerre, formeBarre3D, useRecuLe,
} from "@/components/admin/relief";
import type { Echeance, MoisRevenu, PaiementRecu } from "@/components/admin/types";
import CompteARebours from "@/components/admin/vues/CompteARebours";

const euros = (cents: number | null | undefined, digits = 0) =>
  cents == null ? "—" : eur(cents / 100, digits);
const eurosFin = (cents: number) => eur(cents / 100, cents % 100 ? 2 : 0);

function nomMois(cle: string, long = false) {
  const [a, m] = cle.split("-").map(Number);
  const d = new Date(a, m - 1, 1);
  return long
    ? d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" })
    : d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
}

const dateCourte = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }) : "—";

const NATURE_ECHEANCE: Record<Echeance["nature"], { label: string; ton: "ok" | "attention" | "alerte" | "neutre" }> = {
  renouvellement: { label: "Renouvellement", ton: "ok" },
  premier_prelevement: { label: "1er prélèvement (fin d'essai)", ton: "attention" },
  fin_acces: { label: "Résilié — fin d'accès", ton: "neutre" },
  impaye: { label: "Impayé — relances", ton: "alerte" },
};

/* ─────────────────────────── graphique mensuel ─────────────────────────── */

interface PointGraphe {
  cle: string;
  label: string;
  encaisse: number | null;
  prevu: number | null;
  cumul: number | null;
}

function GrapheMensuel({
  points, selection, onSelection,
}: {
  points: PointGraphe[];
  selection: string | null;
  onSelection: (cle: string) => void;
}) {
  return (
    <div className="h-[340px] w-full sm:h-[380px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={points}
          margin={{ top: 24, right: 8, bottom: 0, left: -8 }}
          onClick={(e: { activeLabel?: string; activePayload?: Array<{ payload: PointGraphe }> } | null) => {
            const p = e?.activePayload?.[0]?.payload;
            if (p && p.encaisse != null) onSelection(p.cle);
          }}
        >
          <defs>
            <linearGradient id="rev-cumul" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#a78bfa" />
              <stop offset="100%" stopColor="#38bdf8" />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 6" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis yAxisId="g" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={56}
            tickFormatter={(v: number) => eur(v)} />
          <YAxis yAxisId="d" orientation="right" hide />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={(p) => (
              <InfobulleVerre
                active={p.active}
                payload={p.payload as never}
                label={p.label}
                formatValeur={(v) => eur(v, 2)}
              />
            )}
          />
          <Bar
            yAxisId="g" dataKey="encaisse" name="Encaissé" fill="#f5b544" maxBarSize={46} cursor="pointer"
            isAnimationActive
            shape={(props: unknown) => {
              const pl = (props as { payload: PointGraphe }).payload;
              const couleur = pl.cle === selection ? "#ffd779" : "#e39a1f";
              return formeBarre3D(couleur, 10)(props);
            }}
          />
          <Bar
            yAxisId="g" dataKey="prevu" name="Prévu (échéancier)" fill="#38bdf8" maxBarSize={46}
            shape={formeBarre3D("#2a86b8", 10)} fillOpacity={0.6}
          />
          <Line
            yAxisId="d" dataKey="cumul" name="Cumul encaissé" type="monotone" stroke="url(#rev-cumul)"
            strokeWidth={2.5} dot={{ r: 3, fill: "#a78bfa", strokeWidth: 0 }} connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ─────────────────────────── détail d'un mois ──────────────────────────── */

const COLONNES_PAIEMENTS: Colonne<PaiementRecu>[] = [
  { titre: "Client", rendu: (p) => <CelluleCompte email={p.email ?? "compte supprimé"} />, className: "max-w-[280px]" },
  { titre: "Formule", rendu: (p) => <BadgeFormule plan={p.plan} /> },
  {
    titre: "Nature",
    rendu: (p) => p.nature === "nouveau"
      ? <Etat ton="or">Nouveau client</Etat>
      : <Etat ton="ok">Renouvellement</Etat>,
  },
  {
    titre: "Encaissé le",
    rendu: (p) => <span className="whitespace-nowrap text-muted-foreground" title={formatDateTime(p.date)}>{dateCourte(p.date)}</span>,
  },
  { titre: "Montant", rendu: (p) => <span className="font-bold text-emerald-300">+{eurosFin(p.montant_cents)}</span>, droite: true },
];

function DetailMois({ m }: { m: MoisRevenu }) {
  const cases = [
    { label: "Nouveaux clients", v: euros(m.nouveaux_cents), icone: <UserPlus className="h-4 w-4" />, c: "text-amber-300" },
    { label: "Renouvellements", v: euros(m.renouvellements_cents), icone: <Repeat className="h-4 w-4" />, c: "text-emerald-300" },
    { label: "Paiements", v: num(m.nb_paiements), icone: <CircleDollarSign className="h-4 w-4" />, c: "text-white" },
    { label: "Clients payants", v: num(m.nb_clients), icone: <Landmark className="h-4 w-4" />, c: "text-white" },
    { label: "Panier moyen", v: euros(m.panier_moyen_cents, 2), icone: <Sparkles className="h-4 w-4" />, c: "text-sky-300" },
    {
      label: "Échecs de prélèvement",
      v: m.nb_echecs ? `${m.nb_echecs} · ${euros(m.echecs_cents)}` : "0",
      icone: <TrendingUp className="h-4 w-4 rotate-180" />,
      c: m.nb_echecs ? "text-red-300" : "text-white/60",
    },
  ];
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[auto_1fr] lg:items-center">
        <div className="flex flex-col items-center gap-3 sm:flex-row lg:flex-col">
          <Anneau3D
            taille={200}
            parts={[
              { cle: "standard", label: "Standard", n: m.par_formule.standard, couleur: "#38bdf8" },
              { cle: "expert", label: "Expert", n: m.par_formule.expert, couleur: "#f5b544" },
            ]}
            centre={
              <div className="rounded-xl bg-black/40 px-3 py-1.5 backdrop-blur">
                <div className="text-[10px] font-semibold uppercase tracking-widest text-white/50">Total</div>
                <div className="bt-or-texte text-xl font-black tabular-nums">{euros(m.encaisse_cents)}</div>
              </div>
            }
          />
          <div className="flex gap-4 text-xs">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-sky-400 shadow-[0_0_8px_#38bdf8]" />Standard <b className="tabular-nums text-white">{euros(m.par_formule.standard)}</b></span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-amber-400 shadow-[0_0_8px_#f5b544]" />Expert <b className="tabular-nums text-white">{euros(m.par_formule.expert)}</b></span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {cases.map((c) => (
            <div key={c.label} className="bt-verre bt-relief rounded-xl p-3">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-white/50">
                <span className="text-white/40">{c.icone}</span>{c.label}
              </div>
              <div className={cn("bt-chiffre-3d mt-1.5 text-xl font-bold tabular-nums", c.c)}>{c.v}</div>
            </div>
          ))}
        </div>
      </div>
      <Tableau
        lignes={m.paiements}
        colonnes={COLONNES_PAIEMENTS}
        cle={(p) => `${p.date}-${p.email}-${p.montant_cents}`}
        label={`Paiements de ${nomMois(m.mois, true)}`}
        vide="Aucun encaissement ce mois-ci."
        limite={10}
      />
    </div>
  );
}

/* ─────────────────────────── tableau récapitulatif ─────────────────────── */

function Recapitulatif({ mois, selection, onSelection }: {
  mois: MoisRevenu[]; selection: string | null; onSelection: (c: string) => void;
}) {
  const max = Math.max(1, ...mois.map((m) => m.encaisse_cents));
  const lignes = [...mois].reverse();
  return (
    <DefilementX label="Revenus mois par mois">
      <table className="w-full min-w-[860px] border-collapse">
        <thead>
          <tr className="border-b border-white/10 bg-white/[0.02]">
            <th className={TH}>Mois</th>
            <th className={cn(TH, "w-[30%]")}>Encaissé</th>
            <th className={cn(TH, "text-right")}>vs mois préc.</th>
            <th className={cn(TH, "text-right")}>Paiements</th>
            <th className={cn(TH, "text-right")}>Nouveaux</th>
            <th className={cn(TH, "text-right")}>Renouv.</th>
            <th className={cn(TH, "text-right")}>Standard</th>
            <th className={cn(TH, "text-right")}>Expert</th>
            <th className={cn(TH, "text-right")}>Échecs</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((m, i) => {
            const prec = lignes[i + 1];
            const variation = prec && prec.encaisse_cents > 0
              ? ((m.encaisse_cents - prec.encaisse_cents) / prec.encaisse_cents) * 100
              : null;
            const actif = m.mois === selection;
            return (
              <tr
                key={m.mois}
                onClick={() => onSelection(m.mois)}
                className={cn("cursor-pointer border-b border-white/[0.05]", actif && "bg-amber-400/[0.07]")}
              >
                <td className={cn(TD, "whitespace-nowrap font-semibold capitalize", actif && "text-amber-300")}>{nomMois(m.mois, true)}</td>
                <td className={TD}>
                  <div className="flex items-center gap-3">
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-black/40 shadow-[inset_0_1px_3px_rgba(0,0,0,0.8)]">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-amber-600 to-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.6)] transition-[width] duration-1000"
                        style={{ width: `${(m.encaisse_cents / max) * 100}%` }}
                      />
                    </div>
                    <span className="w-20 text-right font-bold tabular-nums text-white">{euros(m.encaisse_cents)}</span>
                  </div>
                </td>
                <td className={cn(TD, "text-right tabular-nums font-semibold", variation == null ? "text-white/40" : variation >= 0 ? "text-emerald-300" : "text-red-300")}>
                  {variation == null ? "—" : signedPct(variation, 0)}
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>{num(m.nb_paiements)}</td>
                <td className={cn(TD, "text-right tabular-nums text-amber-200")}>{euros(m.nouveaux_cents)}</td>
                <td className={cn(TD, "text-right tabular-nums text-emerald-200")}>{euros(m.renouvellements_cents)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{euros(m.par_formule.standard)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{euros(m.par_formule.expert)}</td>
                <td className={cn(TD, "text-right tabular-nums", m.nb_echecs ? "text-red-300" : "text-white/40")}>
                  {m.nb_echecs ? `${m.nb_echecs} · ${euros(m.echecs_cents)}` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </DefilementX>
  );
}

/* ─────────────────────────────── échéancier ────────────────────────────── */

const COLONNES_ECHEANCES: Colonne<Echeance>[] = [
  { titre: "Abonné", rendu: (e) => <CelluleCompte email={e.email} />, className: "max-w-[280px]" },
  { titre: "Formule", rendu: (e) => <BadgeFormule plan={e.plan} periodicite={e.periodicite} /> },
  { titre: "Prochaine échéance", rendu: (e) => <CompteARebours date={e.date} jours={e.jours_restants} nature={e.nature} /> },
  {
    titre: "Nature",
    rendu: (e) => <Etat ton={NATURE_ECHEANCE[e.nature].ton}>{NATURE_ECHEANCE[e.nature].label}</Etat>,
  },
  {
    titre: "Montant prévu",
    rendu: (e) => e.montant_cents > 0
      ? <span className="font-bold text-white">{eurosFin(e.montant_cents)}</span>
      : <span className="text-white/40">0 €</span>,
    droite: true,
  },
];

type FiltreEch = "tous" | "7" | "30" | "resilies";

function Echeancier({ echeances }: { echeances: Echeance[] }) {
  const [filtre, setFiltre] = useState<FiltreEch>("30");
  const dans = (e: Echeance, j: number) => e.jours_restants != null && e.jours_restants <= j;
  const somme = (l: Echeance[]) => l.reduce((s, e) => s + e.montant_cents, 0);
  const sous7 = echeances.filter((e) => dans(e, 7) && e.montant_cents > 0);
  const sous30 = echeances.filter((e) => dans(e, 30) && e.montant_cents > 0);
  const resilies = echeances.filter((e) => e.nature === "fin_acces");

  const lignes = filtre === "7" ? echeances.filter((e) => dans(e, 7))
    : filtre === "30" ? echeances.filter((e) => dans(e, 30))
    : filtre === "resilies" ? resilies
    : echeances;

  // Frise des 30 prochains jours : un plot par jour, hauteur = montant attendu.
  const parJour = Array.from({ length: 30 }, (_, i) => {
    const l = echeances.filter((e) => e.jours_restants != null && e.montant_cents > 0 && Math.floor(e.jours_restants) === i);
    return { i, n: l.length, montant: somme(l) };
  });
  const maxJour = Math.max(1, ...parJour.map((d) => d.montant));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-2.5">
        {[
          { l: "Sous 7 jours", v: somme(sous7), n: sous7.length, c: "text-amber-300" },
          { l: "Sous 30 jours", v: somme(sous30), n: sous30.length, c: "text-emerald-300" },
          { l: "Résiliés (fin d'accès)", v: null, n: resilies.length, c: "text-white/70" },
        ].map((k) => (
          <div key={k.l} className="bt-verre rounded-xl p-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-white/50">{k.l}</div>
            <div className={cn("bt-chiffre-3d mt-1 text-xl font-bold tabular-nums", k.c)}>
              {k.v == null ? num(k.n) : euros(k.v)}
            </div>
            {k.v != null && <div className="text-xs text-white/45">{k.n} prélèvement{k.n > 1 ? "s" : ""}</div>}
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3 [perspective:700px]">
        <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.06em] text-white/50">
          <span>Frise des 30 prochains jours</span><span>montant attendu / jour</span>
        </div>
        <div className="flex h-24 items-end gap-[3px] [transform:rotateX(18deg)] [transform-origin:bottom]">
          {parJour.map((d) => (
            <div key={d.i} className="group relative flex h-full flex-1 flex-col justify-end" title={`J+${d.i} : ${d.n} prélèvement(s), ${euros(d.montant)}`}>
              <div
                className={cn(
                  "w-full rounded-t-[3px] transition-all duration-700",
                  d.montant > 0 ? "bg-gradient-to-t from-emerald-700 to-emerald-300 shadow-[0_0_10px_rgba(52,211,153,0.55)]" : "bg-white/[0.05]",
                )}
                style={{ height: d.montant > 0 ? `${12 + (d.montant / maxJour) * 88}%` : "6%" }}
              />
            </div>
          ))}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-white/40"><span>aujourd&apos;hui</span><span>J+15</span><span>J+30</span></div>
      </div>

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
  );
}

/* ───────────────────────────────── page ────────────────────────────────── */

export default function RevenusPage() {
  const [fenetre, setFenetre] = useState<"6" | "12" | "24">("12");
  const { data, isValidating } = useRevenus(Number(fenetre));
  const { data: abos } = useAbonnements();
  const recu = useRecuLe(data);
  const [choix, setChoix] = useState<string | null>(null);

  const points = useMemo<PointGraphe[]>(() => {
    if (!data) return [];
    const courant = data.mois[data.mois.length - 1]?.mois;
    const prev = new Map(data.prevision.map((p) => [p.mois, p.prevu_cents]));
    const passes: PointGraphe[] = data.mois.map((m) => ({
      cle: m.mois,
      label: nomMois(m.mois),
      encaisse: m.encaisse_cents / 100,
      prevu: m.mois === courant && prev.get(m.mois) ? (prev.get(m.mois) ?? 0) / 100 : null,
      cumul: m.cumul_cents / 100,
    }));
    const futurs: PointGraphe[] = data.prevision
      .filter((p) => courant && p.mois > courant)
      .slice(0, 3)
      .map((p) => ({ cle: p.mois, label: `${nomMois(p.mois)}*`, encaisse: null, prevu: p.prevu_cents / 100, cumul: null }));
    return [...passes, ...futurs];
  }, [data]);

  const selection = choix ?? data?.mois[data.mois.length - 1]?.mois ?? null;
  const moisChoisi = data?.mois.find((m) => m.mois === selection);
  const t = data?.totaux;
  const serie = data?.mois.map((m) => m.encaisse_cents / 100);

  return (
    <div className="space-y-5 sm:space-y-6">
      <EnTetePage
        titre="Revenus"
        icone={<Euro className="h-4 w-4" />}
        desc="Encaissements Stripe réels (factures payées), mois par mois — et l'échéancier des prochains prélèvements."
        actions={
          <>
            <Fraicheur depuis={recu} enCours={isValidating && !data} cadence={30_000} />
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
          icone={<Euro className="h-4 w-4" />}
          accent="or"
          tendance={t?.variation_pct}
          tendanceLabel="vs mois précédent"
          serie={serie}
        />
        <Kpi
          label="Atterrissage du mois"
          nombre={t ? t.atterrissage_mois_cents / 100 : null}
          format={(v) => eur(v)}
          icone={<CalendarClock className="h-4 w-4" />}
          accent="bleu"
          sub={t ? `dont ${euros(t.reste_a_encaisser_mois_cents)} encore à prélever` : undefined}
        />
        <Kpi
          label="Revenu mensuel récurrent"
          nombre={abos?.resume.mrr ?? null}
          format={(v) => eur(v)}
          icone={<Repeat className="h-4 w-4" />}
          accent="ok"
          sub={abos ? `${eur(abos.resume.arr)} par an · ${abos.resume.abonnes_payants} payants` : undefined}
        />
        <Kpi
          label={`Total ${fenetre} mois`}
          nombre={t ? t.periode_cents / 100 : null}
          format={(v) => eur(v)}
          icone={<Landmark className="h-4 w-4" />}
          accent="violet"
          sub={t ? `moyenne ${euros(t.moyenne_mensuelle_cents)}/mois · ${num(t.nb_paiements)} paiements` : undefined}
        />
      </GrilleKpi>

      <Panneau
        titre="Revenus par mois"
        desc="Barres or : encaissé réel. Barres bleues : prévu d'après l'échéancier (* = mois à venir). Ligne : cumul. Cliquez un mois pour son détail."
        icone={<TrendingUp className="h-3.5 w-3.5" />}
        ton="or"
        actions={<Puce ton="or">{data ? `${num(t?.nb_paiements)} paiements` : "…"}</Puce>}
      >
        {!data ? <Squelette lignes={8} /> : data.mois.every((m) => m.encaisse_cents === 0) && data.prevision.length === 0
          ? <Vide>Aucun encaissement enregistré sur la période.</Vide>
          : <GrapheMensuel points={points} selection={selection} onSelection={setChoix} />}
      </Panneau>

      {moisChoisi && (
        <div id="detail-mois" className="scroll-mt-20">
        <Panneau
          titre={<span className="capitalize">Détail — {nomMois(moisChoisi.mois, true)}</span>}
          desc="Chaque ligne est une facture Stripe payée, au centime."
          icone={<CircleDollarSign className="h-3.5 w-3.5" />}
          actions={<Puce ton="ok">{euros(moisChoisi.encaisse_cents, 2)}</Puce>}
        >
          <DetailMois m={moisChoisi} />
        </Panneau>
        </div>
      )}

      <Panneau
        titre="Échéancier des abonnés"
        desc="Date du prochain prélèvement de chaque abonnement vivant, et son montant. Un abonnement résilié ne sera plus débité."
        icone={<CalendarClock className="h-3.5 w-3.5" />}
        actions={data ? <Puce>{data.echeancier.length} abonnements</Puce> : undefined}
      >
        {!data ? <Squelette lignes={6} /> : <Echeancier echeances={data.echeancier} />}
      </Panneau>

      <Panneau
        titre="Tableau mois par mois"
        desc="Cliquez une ligne pour afficher le détail du mois au-dessus."
        bodyClassName="p-0 sm:p-0 pt-2"
      >
        {!data ? <div className="p-5"><Squelette lignes={6} /></div>
          : <div className="px-4 pb-4 sm:px-5"><Recapitulatif mois={data.mois} selection={selection} onSelection={(c) => { setChoix(c); document.getElementById("detail-mois")?.scrollIntoView({ behavior: "smooth", block: "start" }); }} /></div>}
      </Panneau>
    </div>
  );
}
