"use client";

/**
 * Abonnements — essais, cartes manquantes, journal Stripe.
 *
 * Ce contenu était une section repliée au milieu de `/admin`, elle-même
 * contenant une seconde section repliée pour le journal. Deux niveaux de
 * dépliage : l'information la plus commerciale du produit était à trois clics
 * et zéro chemin de navigation.
 *
 * Trois choses tenues ici :
 *   · un échec de paiement coupe l'accès — il est remonté en haut, hors de
 *     tout dépliage ;
 *   · on compte les INCIDENTS, pas les lignes du journal : un seul incident
 *     écrit deux mouvements à quelques secondes d'écart (le statut Stripe
 *     `past_due`, puis `paiement_echoue`) ;
 *   · un essai perdu n'est pas une résiliation. Le premier n'a jamais converti,
 *     le second était un client.
 */

import { useState } from "react";
import { AlertTriangle, CreditCard, History, Users2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn, formatDateTime, formatEuro } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, EnTetePage, Encart, GrilleTuiles, Panneau,
  Puce, Squelette, TD, TH, Tuile, VoirPlus, Vide, depuis, num,
} from "@/components/admin/ui";
import { incidentsPaiement, useAbonnements } from "@/components/admin/data";
import {
  MOUVEMENT_LABELS, MOUVEMENT_TONS, type AbonneLigne, type MouvementAbo,
} from "@/components/admin/types";

/** Un statut Stripe brut n'est pas un libellé : « past_due » s'affichait tel
 *  quel dans la colonne « État », en anglais et en serpent. */
const ETATS_STRIPE: Record<string, { texte: string; aide: string }> = {
  past_due: { texte: "Impayé", aide: "Impayé — accès coupé, relances Stripe en cours" },
  unpaid: { texte: "Impayé définitif", aide: "Relances Stripe épuisées" },
  canceled: { texte: "Résilié", aide: "Abonnement clos chez Stripe" },
  incomplete: { texte: "Incomplet", aide: "Paiement jamais finalisé" },
  incomplete_expired: { texte: "Expiré", aide: "Paiement abandonné — abonnement expiré" },
  paused: { texte: "Suspendu", aide: "Abonnement suspendu" },
  cancel_at_period_end: { texte: "Fin de période", aide: "Résilié, mais payé jusqu'à la fin de la période en cours" },
};

/** État d'un abonnement, en un mot. La phrase complète est en infobulle : le
 *  libellé long occupait trois lignes dans sa cellule et repliait la pastille
 *  en un ovale. */
function etatAbonne(a: AbonneLigne) {
  if (!a.carte_enregistree) {
    return (
      <Badge variant="warning" className="text-[11px]" title="Essai ouvert sans carte — aucun accès tant qu'un moyen de paiement n'est pas rattaché">
        Carte manquante
      </Badge>
    );
  }
  if (a.en_essai) return <Badge variant="secondary" className="text-[11px]">Essai en cours</Badge>;
  if (a.acces_ouvert) return <Badge variant="success" className="text-[11px]">Actif</Badge>;
  const st = ETATS_STRIPE[a.statut];
  return (
    <Badge
      variant="secondary"
      className={cn("whitespace-nowrap text-[11px]", a.statut.startsWith("past_due") || a.statut === "unpaid" ? "text-destructive" : undefined)}
      title={st?.aide}
    >
      {st?.texte ?? a.statut}
    </Badge>
  );
}

/** « Starter / mois » — la périodicité ne prend pas de capitale. `capitalize`
 *  posé sur toute la cellule écrivait « Starter / An ». */
function formule(a: AbonneLigne) {
  return (
    <>
      <span className="capitalize">{a.plan}</span>
      <span className="text-xs text-muted-foreground">
        {a.periodicite === "annual" ? " / an" : " / mois"}
      </span>
    </>
  );
}

function finEssai(a: AbonneLigne) {
  if (!a.essai_fin) return <span className="text-muted-foreground">—</span>;
  return (
    <>
      {formatDateTime(a.essai_fin)}
      {a.jours_essai_restants !== null && (
        <span className={cn("ml-1 text-xs", a.jours_essai_restants <= 3 ? "font-semibold text-amber-700" : "text-muted-foreground")}>
          (J−{a.jours_essai_restants})
        </span>
      )}
    </>
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

function montantMouvement(cents: number | null): string | null {
  if (cents == null || cents === 0) return null;
  return `${(cents / 100).toFixed(2).replace(".", ",")} €`;
}

// Habillage d'une ligne de journal. La pastille colorée porte le TON, le libellé
// reste du texte : mis dans une pastille, il faisait varier la largeur du simple
// au quadruple (« Essai ouvert » contre « Impayé — accès coupé, relances Stripe
// en cours ») et plus aucune colonne ne s'alignait d'une ligne à l'autre.
const RAIL: Record<string, { point: string; texte: string; rail: string; fond: string }> = {
  ok: { point: "bg-emerald-600", texte: "text-emerald-800", rail: "border-l-emerald-500/60", fond: "bg-emerald-50/50" },
  attention: { point: "bg-amber-500", texte: "text-amber-800", rail: "border-l-amber-400/70", fond: "bg-amber-50/50" },
  alerte: { point: "bg-destructive", texte: "text-destructive", rail: "border-l-destructive/60", fond: "bg-destructive/[0.04]" },
  neutre: { point: "bg-muted-foreground/40", texte: "text-foreground", rail: "border-l-border", fond: "" },
};

function Journal({ mouvements }: { mouvements: MouvementAbo[] }) {
  const [tout, setTout] = useState(false);
  if (mouvements.length === 0) return <Vide>Aucun mouvement enregistré.</Vide>;
  const visibles = tout ? mouvements : mouvements.slice(0, 10);

  return (
    <>
      <ol className="space-y-1">
        {visibles.map((m, i, liste) => {
          const st = RAIL[MOUVEMENT_TONS[m.type] ?? "neutre"];
          const libelle = MOUVEMENT_LABELS[m.type] ?? m.type;
          const montant = montantMouvement(m.montant_cents);
          const jour = jourMouvement(m.created_at);
          // Séparateur de journée : le journal mélangeait « il y a 5 h » et
          // « il y a 7 j » sans repère, on ne voyait plus ce qui s'était passé
          // aujourd'hui.
          const nouveauJour = i === 0 || jour !== jourMouvement(liste[i - 1].created_at);
          return (
            <li key={m.event_id}>
              {nouveauJour && (
                <div className="flex items-center gap-2 px-1 pb-1 pt-3 first:pt-0">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                    {jour}
                  </span>
                  <span className="h-px flex-1 bg-border" />
                </div>
              )}
              <div className={cn("flex items-start gap-3 rounded-lg border-l-2 py-2.5 pl-3 pr-2", st.rail, st.fond)}>
                <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", st.point)} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className={cn("text-[13px] font-semibold leading-snug", st.texte)}>{libelle}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                    <span className="truncate" title={m.email ?? undefined}>
                      {m.email ?? "compte supprimé"}
                    </span>
                    {m.plan && (
                      <span className="capitalize">
                        · {m.plan_precedent ? `${m.plan_precedent} → ${m.plan}` : m.plan}
                      </span>
                    )}
                    {m.pendant_essai && <span className="text-amber-700">· pendant l&apos;essai</span>}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {montant && <div className="text-[13px] font-semibold tabular-nums">{montant}</div>}
                  <div className="whitespace-nowrap text-xs text-muted-foreground" title={formatDateTime(m.created_at)}>
                    {depuis(m.created_at)}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <VoirPlus total={mouvements.length} montres={10} tout={tout} onToggle={() => setTout((v) => !v)} />
    </>
  );
}

export default function AbonnementsPage() {
  const { data } = useAbonnements();
  const { uniques, dernier } = incidentsPaiement(data);

  return (
    <div className="space-y-4 sm:space-y-5">
      <EnTetePage
        titre="Abonnements"
        icone={<CreditCard className="h-4 w-4" />}
        desc="Essais en cours, cartes manquantes, encaissements et résiliations — tout ce qui décide de l'accès au produit."
        actions={
          <>
            {uniques.length > 0 && (
              <Puce ton="alerte">
                {uniques.length} incident{uniques.length > 1 ? "s" : ""} · 7 j
              </Puce>
            )}
            {data && <Puce ton={data.resume.abonnes_payants > 0 ? "ok" : "neutre"}>{data.resume.abonnes_payants} payant(s)</Puce>}
          </>
        }
      />

      {!data ? (
        <Panneau titre="Chargement"><Squelette lignes={5} /></Panneau>
      ) : (
        <>
          {dernier && (
            <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
              <b>{MOUVEMENT_LABELS[dernier.type] ?? dernier.type}</b>
              {" — "}
              {dernier.email ?? "compte supprimé"}, <span title={formatDateTime(dernier.created_at)}>{depuis(dernier.created_at)}</span>.
              {uniques.length > 1 && ` ${uniques.length - 1} autre${uniques.length > 2 ? "s" : ""} incident${uniques.length > 2 ? "s" : ""} sur 7 jours.`}
              {" "}L&apos;accès est coupé dès le premier échec — Stripe relance la carte, pas nous.
            </Encart>
          )}

          <Panneau
            titre="État du parc"
            desc="Photo de l'instant. « Sans carte » ne veut pas dire « en attente » : sans moyen de paiement rattaché, l'accès est bloqué."
            icone={<Users2 className="h-3.5 w-3.5" />}
          >
            <GrilleTuiles colonnes={6}>
              <Tuile label="Payants" valeur={num(data.resume.abonnes_payants)} ton={data.resume.abonnes_payants > 0 ? "ok" : "neutre"} />
              <Tuile label="En essai" valeur={num(data.resume.en_essai_avec_carte)} />
              <Tuile
                label="Sans carte"
                valeur={num(data.resume.en_essai_sans_carte)}
                ton={data.resume.en_essai_sans_carte > 0 ? "attention" : "neutre"}
                sub={data.resume.en_essai_sans_carte > 0 ? "accès bloqué" : undefined}
              />
              <Tuile
                label="Fin d'essai < 3 j"
                valeur={num(data.resume.fin_essai_sous_3j)}
                ton={data.resume.fin_essai_sous_3j > 0 ? "attention" : "neutre"}
              />
              <Tuile label="Revenu mensuel" valeur={formatEuro(data.resume.mrr)} sub={`ARR ${formatEuro(data.resume.arr)}`} />
              <Tuile label="Résiliations 30 j" valeur={num(data.resume.resiliations_30j)} />
            </GrilleTuiles>

            <Encart>
              Sur 30 jours : <b>{data.resume.essais_ouverts_30j}</b> essai(s) ouvert(s),{" "}
              <b>{data.resume.essais_perdus_30j}</b> perdu(s) faute de carte,{" "}
              <b>{data.resume.resiliations_pendant_essai_30j}</b> résiliation(s) survenue(s)
              pendant l&apos;essai. Un essai perdu n&apos;est pas une résiliation : le premier
              n&apos;a jamais converti, le second était un client.
            </Encart>
          </Panneau>

          <Panneau
            titre="Abonnements en cours"
            desc={`${data.abonnes.length} ligne(s) — un abonnement par compte, montant réellement facturé.`}
            actions={<Puce>{data.abonnes.length}</Puce>}
          >
            {data.abonnes.length === 0 ? (
              <Vide>Aucun abonnement en cours.</Vide>
            ) : (
              <CartesOuTableau
                cartes={data.abonnes.map((a) => (
                  <Carte
                    key={a.stripe_subscription_id ?? a.user_id}
                    ton={!a.carte_enregistree ? "attention" : "neutre"}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{a.email}</span>
                      <span className="shrink-0 text-[13px] font-semibold tabular-nums">
                        {formatEuro(a.montant_cents / 100)}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge variant="secondary" className="text-[11px]">{formule(a)}</Badge>
                      {etatAbonne(a)}
                    </div>
                    {a.essai_fin && (
                      <div className="mt-2 border-t border-border/60 pt-2">
                        <Champ label="Fin d'essai">{finEssai(a)}</Champ>
                      </div>
                    )}
                  </Carte>
                ))}
                tableau={
                  <DefilementX label="Abonnements en cours">
                    <table className="w-full min-w-[680px] border-collapse">
                      <thead>
                        <tr className="border-b border-border">
                          <th className={TH}>Compte</th>
                          <th className={TH}>Formule</th>
                          <th className={TH}>État</th>
                          <th className={TH}>Fin d&apos;essai</th>
                          <th className={cn(TH, "text-right")}>Montant</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.abonnes.map((a) => (
                          <tr
                            key={a.stripe_subscription_id ?? a.user_id}
                            className="border-b border-border/40 last:border-0 hover:bg-muted/30"
                          >
                            <td className={cn(TD, "max-w-[260px] truncate")} title={a.email}>{a.email}</td>
                            <td className={cn(TD, "whitespace-nowrap")}>{formule(a)}</td>
                            <td className={TD}>{etatAbonne(a)}</td>
                            <td className={cn(TD, "whitespace-nowrap")}>{finEssai(a)}</td>
                            <td className={cn(TD, "text-right tabular-nums whitespace-nowrap")}>
                              {formatEuro(a.montant_cents / 100)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </DefilementX>
                }
              />
            )}
          </Panneau>

          <Panneau
            titre="Journal des mouvements"
            desc="Ce que Stripe a réellement enregistré : essais, cartes, encaissements, résiliations. Groupé par journée."
            icone={<History className="h-3.5 w-3.5" />}
            actions={<Puce>{data.mouvements.length} mouvement(s)</Puce>}
          >
            <Journal mouvements={data.mouvements} />
          </Panneau>
        </>
      )}
    </div>
  );
}
