"use client";

/**
 * Abonnements — qui paie, qui essaie, qui a un accès offert, qui est gratuit.
 *
 * Refonte du 2026-09-14 : l'écran empilait six tuiles, trois paragraphes
 * d'explication et deux listes, et l'exploitant le jugeait illisible. Il répond
 * maintenant à quatre questions, dans cet ordre : combien ça rapporte, comment se
 * répartissent les comptes, qui est dans chaque case, ce qui s'est passé.
 *
 * Règles gardées de la version précédente :
 *   · on compte les INCIDENTS de paiement, pas les lignes du journal (un échec
 *     écrit `past_due` puis `paiement_echoue` à quelques secondes d'écart) ;
 *   · un essai perdu n'est pas une résiliation.
 */

import { useState } from "react";
import { AlertTriangle, CreditCard, Gift, Hourglass, Wallet } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, BarreRepartition, CelluleCompte, EnTetePage, Encart, Etat, GrilleKpi, Kpi,
  Panneau, PointLive, Puce, Segments, Squelette, TH, Tableau, VoirPlus, Vide, depuis, eur, num,
  type Colonne,
} from "@/components/admin/ui";
import { incidentsPaiement, useAbonnements, useEnLigne } from "@/components/admin/data";
import SuiviDeparts from "@/components/admin/vues/SuiviDeparts";
import {
  MOUVEMENT_LABELS, MOUVEMENT_TONS,
  type AbonneLigne, type CompteOffert, type MouvementAbo, type Repartition,
} from "@/components/admin/types";

type Onglet = "payants" | "essais" | "offerts" | "journal";

/** Un statut Stripe brut n'est pas un libellé. */
const ETATS_STRIPE: Record<string, string> = {
  past_due: "Impayé",
  unpaid: "Impayé définitif",
  canceled: "Résilié",
  incomplete: "Incomplet",
  incomplete_expired: "Expiré",
  paused: "Suspendu",
  cancel_at_period_end: "Fin de période",
};

const dateCourte = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" }) : "—";

const montant = (cents: number) => eur(cents / 100, cents % 100 ? 2 : 0);

/* ───────────────────────────── colonnes ───────────────────────────── */

function etatPayant(a: AbonneLigne) {
  if (a.statut === "cancel_at_period_end") return <Etat ton="attention" titre="Résilié, payé jusqu'à la fin de la période">Fin de période</Etat>;
  if (a.acces_ouvert) return <Etat ton="ok">Actif</Etat>;
  const alerte = a.statut === "past_due" || a.statut === "unpaid";
  return (
    <Etat ton={alerte ? "alerte" : "neutre"} titre={alerte ? "Accès coupé, relances Stripe en cours" : undefined}>
      {ETATS_STRIPE[a.statut] ?? a.statut}
    </Etat>
  );
}

/** Jours restants en barre : on voit d'un coup d'œil qui arrive au bout. */
function FinEssai({ a }: { a: AbonneLigne }) {
  if (!a.essai_fin) return <span className="text-muted-foreground">—</span>;
  const j = a.jours_essai_restants;
  const urgent = j != null && j <= 3;
  return (
    <div className="ml-auto w-full min-w-[9rem] max-w-[12rem] md:ml-0">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className={cn("font-semibold tabular-nums", urgent ? "text-amber-700" : "text-foreground")}>
          {j != null ? `J−${Math.max(0, Math.ceil(j))}` : "Terminé"}
        </span>
        <span className="text-muted-foreground" title={formatDateTime(a.essai_fin)}>
          {new Date(a.essai_fin).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", urgent ? "bg-amber-500" : "bg-sky-500")}
          style={{ width: `${j != null ? Math.max(4, Math.min(100, (j / 7) * 100)) : 0}%` }}
        />
      </div>
      {a.statut === "cancel_at_period_end" && (
        <div className="mt-1 text-xs font-medium text-amber-700">Résilié — ne sera pas débité</div>
      )}
    </div>
  );
}

const COLONNES_PAYANTS: Colonne<AbonneLigne>[] = [
  { titre: "Compte", rendu: (a) => <CelluleCompte email={a.email} />, className: "max-w-[300px]" },
  { titre: "Formule", rendu: (a) => <BadgeFormule plan={a.plan} periodicite={a.periodicite} /> },
  { titre: "État", rendu: etatPayant },
  { titre: "Client depuis", rendu: (a) => <span className="whitespace-nowrap">{dateCourte(a.depuis)}</span> },
  { titre: "Montant", rendu: (a) => <span className="font-semibold">{montant(a.montant_cents)}</span>, droite: true },
];

const COLONNES_ESSAIS: Colonne<AbonneLigne>[] = [
  { titre: "Compte", rendu: (a) => <CelluleCompte email={a.email} />, className: "max-w-[300px]" },
  { titre: "Formule", rendu: (a) => <BadgeFormule plan={a.plan} /> },
  {
    titre: "Carte",
    rendu: (a) => a.carte_enregistree
      ? <Etat ton="ok">Enregistrée</Etat>
      : <Etat ton="attention" titre="Aucun accès tant qu'un moyen de paiement n'est pas rattaché">Manquante</Etat>,
  },
  { titre: "Fin d'essai", rendu: (a) => <FinEssai a={a} /> },
];

const COLONNES_OFFERTS: Colonne<CompteOffert>[] = [
  { titre: "Compte", rendu: (o) => <CelluleCompte email={o.email} />, className: "max-w-[300px]" },
  { titre: "Accès", rendu: (o) => <BadgeFormule plan={o.plan} /> },
  { titre: "Inscrit le", rendu: (o) => <span className="whitespace-nowrap">{dateCourte(o.created_at)}</span> },
  {
    titre: "Dernière connexion",
    rendu: (o) => <span className="whitespace-nowrap text-muted-foreground" title={o.last_login ? formatDateTime(o.last_login) : undefined}>{depuis(o.last_login)}</span>,
    droite: true,
  },
];

/* ───────────────────────────── blocs ───────────────────────────── */

function Formules({ r }: { r: Repartition }) {
  const cellule = "px-3 py-2.5 text-right text-[13px] font-semibold tabular-nums";
  return (
    <div className="mt-5 overflow-hidden rounded-xl border border-border/70">
      <table className="w-full border-collapse">
        <thead className="bg-muted/40">
          <tr>
            <th scope="col" className={cn(TH, "px-3")}>Formule</th>
            <th scope="col" className={cn(TH, "px-3 text-right")}>Payants</th>
            <th scope="col" className={cn(TH, "px-3 text-right")}>En essai</th>
            <th scope="col" className={cn(TH, "px-3 text-right")}>Offerts</th>
          </tr>
        </thead>
        <tbody>
          {(["standard", "expert"] as const).map((f) => (
            <tr key={f} className="border-t border-border/60">
              <th scope="row" className="px-3 py-2.5 text-left"><BadgeFormule plan={f} /></th>
              <td className={cellule}>{num(r.par_formule[f].payants)}</td>
              <td className={cellule}>{num(r.par_formule[f].essais)}</td>
              <td className={cellule}>{num(r.par_formule[f].offerts)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** « Aujourd'hui » / « Hier » / « mardi 24 août » — sépare le journal par journée. */
function jourMouvement(iso: string): string {
  const d = new Date(iso);
  const minuit = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const jours = Math.round((minuit(new Date()) - minuit(d)) / 86_400_000);
  if (jours <= 0) return "Aujourd'hui";
  if (jours === 1) return "Hier";
  return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

const POINT_TON: Record<string, string> = {
  ok: "bg-emerald-500", attention: "bg-amber-500", alerte: "bg-red-500", neutre: "bg-slate-300",
};

function Journal({ mouvements }: { mouvements: MouvementAbo[] }) {
  const [tout, setTout] = useState(false);
  if (mouvements.length === 0) return <Vide>Aucun mouvement enregistré.</Vide>;
  const visibles = tout ? mouvements : mouvements.slice(0, 12);

  return (
    <>
      <ol>
        {visibles.map((m, i, liste) => {
          const ton = MOUVEMENT_TONS[m.type] ?? "neutre";
          const jour = jourMouvement(m.created_at);
          const nouveauJour = i === 0 || jour !== jourMouvement(liste[i - 1].created_at);
          const somme = m.montant_cents ? montant(m.montant_cents) : null;
          return (
            <li key={m.event_id}>
              {nouveauJour && (
                <div className="pb-1 pt-4 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground first:pt-0">
                  {jour}
                </div>
              )}
              <div className="flex items-center gap-3 border-b border-border/50 py-2.5 last:border-0">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", POINT_TON[ton])} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className={cn("truncate text-[13px] font-medium", ton === "alerte" && "text-red-700")}>
                    {MOUVEMENT_LABELS[m.type] ?? m.type}
                  </div>
                  <div className="truncate text-xs text-muted-foreground" title={m.email ?? undefined}>
                    {m.email ?? "compte supprimé"}
                    {m.plan && <span className="capitalize"> · {m.plan_precedent ? `${m.plan_precedent} → ${m.plan}` : m.plan}</span>}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {somme && <div className="text-[13px] font-semibold tabular-nums">{somme}</div>}
                  <div className="whitespace-nowrap text-xs text-muted-foreground" title={formatDateTime(m.created_at)}>
                    {depuis(m.created_at)}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <VoirPlus total={mouvements.length} montres={12} tout={tout} onToggle={() => setTout((v) => !v)} />
    </>
  );
}

/* ───────────────────────────── page ───────────────────────────── */

export default function AbonnementsPage() {
  const { data } = useAbonnements();
  const { data: live } = useEnLigne();
  const [onglet, setOnglet] = useState<Onglet>("payants");
  const { uniques, dernier } = incidentsPaiement(data);

  const entete = (
    <EnTetePage
      titre="Abonnements"
      icone={<CreditCard className="h-4 w-4" />}
      actions={live?.disponible ? (
        <span className="inline-flex h-9 items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 text-[13px] font-semibold text-emerald-800">
          <PointLive /> {num(live.total)} en ligne
        </span>
      ) : undefined}
    />
  );

  if (!data) {
    return (
      <div className="space-y-5 sm:space-y-6">
        {entete}
        <GrilleKpi>
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-[7.25rem] animate-pulse rounded-2xl bg-muted" />)}
        </GrilleKpi>
        <Panneau><Squelette lignes={6} /></Panneau>
      </div>
    );
  }

  const r = data.repartition;
  // Un impayé n'est plus un payant : il vit dans « Essais, résiliations et impayés ».
  const payants = data.abonnes.filter(
    (a) => a.carte_enregistree && !a.en_essai && a.statut !== "past_due" && a.statut !== "unpaid",
  );
  const essais = data.abonnes
    .filter((a) => a.en_essai || !a.carte_enregistree)
    .sort((a, b) => (a.jours_essai_restants ?? 99) - (b.jours_essai_restants ?? 99));
  const s = data.resume;

  const onglets = [
    { key: "payants", label: `Payants · ${payants.length}` },
    { key: "essais", label: `Essais · ${essais.length}` },
    { key: "offerts", label: `Offerts · ${data.offerts.length}` },
    { key: "journal", label: "Journal" },
  ] as const;

  return (
    <div className="space-y-5 sm:space-y-6">
      {entete}

      {dernier && (
        <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
          <b>{uniques.length} incident{uniques.length > 1 ? "s" : ""} de paiement sur 7 jours</b>
          {" — dernier : "}{MOUVEMENT_LABELS[dernier.type] ?? dernier.type}, {dernier.email ?? "compte supprimé"},{" "}
          <span title={formatDateTime(dernier.created_at)}>{depuis(dernier.created_at)}</span>.
        </Encart>
      )}

      <GrilleKpi>
        <Kpi label="Revenu mensuel" valeur={eur(s.mrr)} sub={`${eur(s.arr)} par an`} icone={<Wallet className="h-4 w-4" />} accent="or" />
        <Kpi
          label="Payants"
          valeur={num(r.payants)}
          sub={`Standard ${r.par_formule.standard.payants} · Expert ${r.par_formule.expert.payants}`}
          icone={<CreditCard className="h-4 w-4" />}
          accent="ok"
        />
        <Kpi
          label="En essai"
          valeur={num(r.essais)}
          sub={s.en_essai_sans_carte > 0
            ? `dont ${s.en_essai_sans_carte} sans carte`
            : s.fin_essai_sous_3j > 0
              ? `${s.fin_essai_sous_3j} finissent sous 3 j`
              : `Standard ${r.par_formule.standard.essais} · Expert ${r.par_formule.expert.essais}`}
          icone={<Hourglass className="h-4 w-4" />}
          accent="bleu"
        />
        <Kpi
          label="Offerts"
          valeur={num(r.offerts)}
          sub={`Standard ${r.par_formule.standard.offerts} · Expert ${r.par_formule.expert.offerts}`}
          icone={<Gift className="h-4 w-4" />}
          accent="violet"
        />
      </GrilleKpi>

      {data.suivi && (
        <div id="departs" className="scroll-mt-20">
          <SuiviDeparts suivi={data.suivi} />
        </div>
      )}

      <Panneau titre="Répartition des comptes" actions={<Puce>{num(r.comptes)} comptes</Puce>}>
        <BarreRepartition
          total={r.comptes}
          segments={[
            { cle: "payants", label: "Payants", n: r.payants, couleur: "bg-emerald-500" },
            { cle: "essais", label: "En essai", n: r.essais, couleur: "bg-sky-500" },
            { cle: "offerts", label: "Offerts", n: r.offerts, couleur: "bg-violet-500" },
            { cle: "gratuits", label: "Gratuits", n: r.gratuits, couleur: "bg-slate-300" },
          ]}
        />
        <Formules r={r} />
      </Panneau>

      <Panneau bodyClassName="p-0 sm:p-0">
        <div className="border-b border-border/60 p-2 sm:px-4">
          <Segments
            items={onglets}
            actif={onglet}
            onChange={setOnglet}
            className="border-0 bg-transparent p-0 shadow-none"
          />
        </div>
        <div className="p-4 sm:p-5">
          {onglet === "payants" && (
            <Tableau
              lignes={payants}
              colonnes={COLONNES_PAYANTS}
              cle={(a) => a.stripe_subscription_id ?? a.user_id}
              label="Abonnés payants"
              vide="Aucun abonné payant pour l'instant."
            />
          )}
          {onglet === "essais" && (
            <Tableau
              lignes={essais}
              colonnes={COLONNES_ESSAIS}
              cle={(a) => a.stripe_subscription_id ?? a.user_id}
              label="Essais en cours"
              vide="Aucun essai en cours."
            />
          )}
          {onglet === "offerts" && (
            <Tableau
              lignes={data.offerts}
              colonnes={COLONNES_OFFERTS}
              cle={(o) => o.user_id}
              label="Accès offerts"
              vide="Aucun accès offert. Un plan payant accordé à la main depuis « Comptes » apparaît ici."
            />
          )}
          {onglet === "journal" && (
            <>
              <p className="mb-3 text-xs text-muted-foreground">
                30 derniers jours : <b className="text-foreground">{s.essais_ouverts_30j}</b> essais ouverts ·{" "}
                <b className="text-foreground">{s.essais_perdus_30j}</b> perdus sans carte ·{" "}
                <b className="text-foreground">{s.resiliations_30j}</b> résiliations
              </p>
              <Journal mouvements={data.mouvements} />
            </>
          )}
        </div>
      </Panneau>
    </div>
  );
}
