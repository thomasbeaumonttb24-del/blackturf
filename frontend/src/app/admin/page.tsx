"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  Users, Brain, Activity, AlertTriangle, RefreshCw, Loader2,
  CheckCircle, XCircle, Clock, X, Wallet, TrendingUp, CreditCard,
  History, Radio, UserCog
} from "lucide-react";
import { AdminSection, Puce, Tuile, VoirPlus, depuis } from "@/components/admin/Section";

const PROFIL_NET_LABELS: Record<string, string> = {
  conservateur: "Prudent", equilibre: "Modéré", agressif: "Risqué",
};
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useRequireAuth } from "@/hooks/useAuth";
import { adminApi, statsApi } from "@/lib/api";
import { formatDateTime, formatEuro, cn } from "@/lib/utils";

interface DashboardData {
  users: { total: number; nouveaux_7j: number; abonnes_actifs: number };
  modele: { version: number | null; auc_roc: number | null; precision_top3: number | null; trained_at: string | null };
  courses_24h: number;
  alertes_erreur: number;
}

interface ModelVersion {
  version_num: number;
  auc_roc: number;
  brier_score: number;
  precision_top3: number | null;
  roi_simule: number | null;
  walk_forward_auc: number | null;
  walk_forward_variance: number | null;
  /** Nombre de PARTANTS d'entraînement (~9,3 par course), pas de courses :
   *  la colonne SQL porte ce nom depuis la migration 0001. */
  nb_courses_train: number;
  est_actif: boolean;
  est_rollback: boolean;
  created_at: string;
}

interface SystemError {
  id: number | null;
  kind: string;
  created_at: string | null;
  source: string;
  level: string;
  message: string;
  detail: string | null;
  endpoint: string | null;
  resolved: boolean;
}

interface ScraperStatus {
  [source: string]: { statut: string; derniere_maj: string | null; duree_ms: number | null; erreur: string | null };
}

interface AbonneLigne {
  user_id: string;
  email: string;
  plan: string;
  periodicite: string;
  statut: string;
  carte_enregistree: boolean;
  acces_ouvert: boolean;
  en_essai: boolean;
  essai_fin: string | null;
  jours_essai_restants: number | null;
  periode_fin: string | null;
  montant_cents: number;
  stripe_subscription_id: string | null;
  depuis: string;
}

interface MouvementAbo {
  event_id: string;
  type: string;
  email: string | null;
  plan: string | null;
  plan_precedent: string | null;
  montant_cents: number | null;
  essai_fin: string | null;
  pendant_essai: boolean | null;
  created_at: string;
}

interface AbonnementsData {
  resume: {
    en_essai_avec_carte: number;
    en_essai_sans_carte: number;
    abonnes_payants: number;
    fin_essai_sous_3j: number;
    mrr: number;
    arr: number;
    essais_ouverts_30j: number;
    essais_perdus_30j: number;
    resiliations_30j: number;
    resiliations_pendant_essai_30j: number;
  };
  abonnes: AbonneLigne[];
  mouvements: MouvementAbo[];
}

// Libellés du journal. Doit rester aligné sur `services/abonnements.LIBELLES`.
const MOUVEMENT_LABELS: Record<string, string> = {
  essai_ouvert: "Essai ouvert",
  essai_sans_carte: "Essai sans carte",
  carte_ajoutee: "Carte enregistrée",
  abonnement_actif: "Abonnement actif",
  changement_plan: "Changement de formule",
  essai_bientot_fini: "Essai bientôt fini",
  essai_termine_sans_carte: "Essai perdu (sans carte)",
  resiliation_demandee: "Résiliation demandée",
  resilie: "Résilié",
  paiement_echoue: "Paiement échoué — accès coupé",
  paiement_recu: "Paiement encaissé — accès rétabli",
  essai_refuse_carte_reutilisee: "Essai refusé — carte d'un autre compte",
  carte_refusee_autre_compte: "Abonnement refusé — carte d'un autre compte",
  // Statuts Stripe bruts : `_handle_subscription_updated` les journalise tels quels
  // quand le changement ne correspond à aucun mouvement métier nommé. Sans libellé,
  // le journal affichait « past_due » en toutes lettres.
  past_due: "Impayé — accès coupé, relances Stripe en cours",
  unpaid: "Impayé définitif — relances Stripe épuisées",
  canceled: "Abonnement clos chez Stripe",
  incomplete: "Paiement jamais finalisé",
  incomplete_expired: "Paiement abandonné — abonnement expiré",
  paused: "Abonnement suspendu",
};

const MOUVEMENT_TONS: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  carte_ajoutee: "success",
  abonnement_actif: "success",
  essai_ouvert: "secondary",
  changement_plan: "secondary",
  essai_sans_carte: "warning",
  essai_bientot_fini: "warning",
  essai_termine_sans_carte: "destructive",
  resiliation_demandee: "destructive",
  resilie: "destructive",
  paiement_echoue: "destructive",
  paiement_recu: "success",
  essai_refuse_carte_reutilisee: "warning",
  carte_refusee_autre_compte: "destructive",
  past_due: "destructive",
  unpaid: "destructive",
  canceled: "secondary",
  incomplete: "warning",
  incomplete_expired: "secondary",
  paused: "warning",
};

/** Mouvements qui coupent l'accès ou font perdre un client : remontés hors du journal.
 *  `past_due` et `unpaid` en font partie : quand les relances Stripe s'épuisent,
 *  l'abonnement bascule en impayé sans qu'aucune facture n'échoue au même instant. */
const MOUVEMENTS_ECHEC = new Set([
  "paiement_echoue",
  "past_due",
  "unpaid",
  "essai_termine_sans_carte",
  "essai_refuse_carte_reutilisee",
  "carte_refusee_autre_compte",
]);

function StatCard({
  icon: Icon, label, value, sub, ton = "neutre",
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  ton?: "neutre" | "ok" | "alerte" | "attention";
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border bg-card p-3 shadow-sm transition-colors sm:p-4",
        ton === "alerte" ? "border-destructive/30 bg-destructive/[0.03]" : "border-border hover:border-brand-gold/40",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
            ton === "alerte" ? "bg-destructive/10 text-destructive" : "bg-brand-gold/10 text-brand-gold-dark",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        {/* Pas de `truncate` : « Alertes en erreur » se coupait en « ALERTES EN ERRE… »
            à 390 px. Un libellé de tuile doit s'écrire en entier, quitte à passer
            sur deux lignes — c'est ce qui nomme le chiffre juste en dessous. */}
        <span className="text-[10px] font-semibold uppercase leading-tight tracking-wide text-muted-foreground sm:text-[11px]">
          {label}
        </span>
      </div>
      <div className={cn("mt-2 text-2xl font-bold tabular-nums", ton === "alerte" && "text-destructive")}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

interface UserDetail {
  user: {
    user_id: string; email: string; nom: string | null; prenom: string | null;
    plan: string; is_active: boolean; is_admin: boolean; profil_risque: string;
    bankroll_initiale: number | null; email_verified: boolean; auth_method: string;
    stripe_client: boolean; created_at: string; updated_at: string; last_login: string | null;
  };
  portefeuille: {
    capital_initial: number; solde_actuel: number; mise_totale: number; gain_net: number;
    roi: number | null; nb_paris: number; nb_gagnes: number; nb_perdus: number;
    nb_attente: number; nb_regles: number; win_rate: number | null; nb_predictions_used: number;
  };
  par_type: Array<{ type_pari: string; nb: number; mise: number; net: number; nb_gagnes: number; roi: number | null }>;
  subscriptions: Array<{ sub_id: string; plan: string; periodicite: string; statut: string; periode_debut: string | null; periode_fin: string | null }>;
  nb_bets: number;
  bets: Array<{
    entry_id: string; date: string; type_pari: string; chevaux: string | null;
    mise: number; cote: number | null; resultat: string | null; gain_perte: number | null;
    suivi_reco_ia: boolean; notes: string | null; course_code: string | null;
    hippodrome: string | null; course_date: string | null; course_statut: string | null;
  }>;
}

// Habillage d'une ligne de journal. La pastille colorée porte le TON, le libellé
// reste du texte : mis dans une pastille, il faisait varier la largeur du simple
// au quadruple (« Essai ouvert » contre « Impayé — accès coupé, relances Stripe
// en cours ») et plus aucune colonne ne s'alignait d'une ligne à l'autre.
const TON_MOUVEMENT: Record<string, { point: string; texte: string; rail: string; fond: string }> = {
  success:     { point: "bg-green-600",           texte: "text-green-800",  rail: "border-l-green-500/60",   fond: "bg-green-50/50" },
  warning:     { point: "bg-amber-500",           texte: "text-amber-800",  rail: "border-l-amber-400/70",   fond: "bg-amber-50/50" },
  destructive: { point: "bg-destructive",         texte: "text-destructive", rail: "border-l-destructive/60", fond: "bg-destructive/[0.04]" },
  secondary:   { point: "bg-muted-foreground/40", texte: "text-foreground",  rail: "border-l-border",         fond: "" },
};

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

function resultBadge(r: string | null) {
  if (r === "gagne") return <Badge variant="success" className="text-[10px]">Gagné</Badge>;
  if (r === "perd") return <Badge variant="secondary" className="text-[10px] text-destructive">Perdu</Badge>;
  if (r === "annule") return <Badge variant="secondary" className="text-[10px]">Annulé</Badge>;
  return <Badge variant="warning" className="text-[10px]">En attente</Badge>;
}

// Statut réel de l'abonnement — distinct de "a un customer_id Stripe" (créé dès le
// clic sur "S'abonner", avant même que la personne remplisse sa carte). `null` avec
// `stripeClient=true` = checkout démarré et jamais terminé (abandon).
function subBadge(statut: string | null, stripeClient: boolean) {
  if (statut === "active" || statut === "trialing")
    return <Badge variant="success" className="text-[10px]">{statut === "trialing" ? "Essai" : "Actif"}</Badge>;
  if (statut === "cancel_at_period_end")
    return <Badge variant="warning" className="whitespace-nowrap text-[10px]" title="Résilié, mais payé jusqu'à la fin de la période en cours">Fin de période</Badge>;
  // Depuis le 2026-08-27, `past_due` ne donne PLUS accès au produit : Stripe
  // relance la carte pendant des semaines, l'accès est coupé dès le premier échec.
  //
  // Libellé COURT dans le tableau, phrase entière en `title` : le libellé complet
  // occupait trois lignes dans sa cellule et repliait la pastille en un ovale.
  if (statut === "past_due")
    return <Badge variant="secondary" className="whitespace-nowrap text-[10px] text-destructive" title="Impayé — accès coupé, relances Stripe en cours">Impayé</Badge>;
  if (statut === "unpaid")
    return <Badge variant="secondary" className="whitespace-nowrap text-[10px] text-destructive" title="Impayé définitif — relances Stripe épuisées">Impayé définitif</Badge>;
  if (statut === "canceled")
    return <Badge variant="secondary" className="whitespace-nowrap text-[10px] text-muted-foreground">Résilié</Badge>;
  if (statut === "incomplete" || statut === "incomplete_expired")
    return <Badge variant="secondary" className="whitespace-nowrap text-[10px] text-amber-700" title="Paiement jamais finalisé">Incomplet</Badge>;
  if (statut === "essai_sans_carte")
    return <Badge variant="warning" className="whitespace-nowrap text-[10px]" title="Essai ouvert sans carte — aucun accès tant qu'un moyen de paiement n'est pas rattaché">Sans carte</Badge>;
  if (stripeClient)
    return <Badge variant="secondary" className="whitespace-nowrap text-[10px] text-muted-foreground" title="Client Stripe créé, jamais d'abonnement finalisé">Checkout abandonné</Badge>;
  return <span className="text-muted-foreground text-xs">—</span>;
}

function lastLoginLabel(v: string | null) {
  if (!v) return <span className="text-muted-foreground">Jamais</span>;
  return formatDateTime(v);
}

function UserDetailModal({ userId, onClose }: { userId: string; onClose: () => void }) {
  const { data, isLoading } = useSWR<UserDetail>(
    ["/admin-user-detail", userId],
    () => adminApi.userDetail(userId).then((r) => r.data),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-2 sm:p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="relative my-4 sm:my-8 w-full max-w-4xl rounded-2xl border border-border bg-background shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute right-4 top-4 rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
          <X className="h-5 w-5" />
        </button>

        {isLoading || !data ? (
          <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="p-4 sm:p-6 space-y-5 sm:space-y-6">
            {/* Identité */}
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-xl font-bold">{[data.user.prenom, data.user.nom].filter(Boolean).join(" ") || "—"}</h2>
                {data.user.is_admin && <Badge variant="secondary" className="text-[9px]">ADMIN</Badge>}
                <Badge variant={data.user.plan === "expert" ? "expert" : ["starter", "standard"].includes(data.user.plan) ? "gold" : "secondary"} className="text-[10px]">{data.user.plan}</Badge>
                {data.user.is_active
                  ? <Badge variant="success" className="text-[10px]">Actif</Badge>
                  : <Badge variant="secondary" className="text-[10px] text-destructive">Suspendu</Badge>}
              </div>
              <div className="mt-1 text-sm text-muted-foreground flex items-center gap-2 flex-wrap">
                <span>{data.user.email}</span>
                <span>· {data.user.auth_method === "google" ? "Google" : "Email"}</span>
                <span>· Profil {data.user.profil_risque}</span>
                <span>· Inscrit {formatDateTime(data.user.created_at)}</span>
                <span>· Vu {lastLoginLabel(data.user.last_login)}</span>
              </div>
            </div>

            {/* Portefeuille — synthèse */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg bg-muted/30 p-3">
                <div className="text-xs text-muted-foreground">Solde actuel</div>
                <div className="text-lg font-bold tabular-nums">{formatEuro(data.portefeuille.solde_actuel)}</div>
                <div className="text-[10px] text-muted-foreground">capital {formatEuro(data.portefeuille.capital_initial)}</div>
              </div>
              <div className="rounded-lg bg-muted/30 p-3">
                <div className="text-xs text-muted-foreground">Gain net</div>
                <div className={cn("text-lg font-bold tabular-nums", data.portefeuille.gain_net >= 0 ? "text-green-700" : "text-destructive")}>
                  {data.portefeuille.gain_net >= 0 ? "+" : ""}{formatEuro(data.portefeuille.gain_net)}
                </div>
                <div className="text-[10px] text-muted-foreground">misé {formatEuro(data.portefeuille.mise_totale)}</div>
              </div>
              <div className="rounded-lg bg-muted/30 p-3">
                <div className="text-xs text-muted-foreground">ROI</div>
                <div className={cn("text-lg font-bold tabular-nums", data.portefeuille.roi == null ? "text-muted-foreground" : data.portefeuille.roi >= 0 ? "text-green-700" : "text-destructive")}>
                  {data.portefeuille.roi == null ? "—" : `${data.portefeuille.roi >= 0 ? "+" : ""}${data.portefeuille.roi}%`}
                </div>
                <div className="text-[10px] text-muted-foreground">{data.portefeuille.nb_predictions_used} suivis IA</div>
              </div>
              <div className="rounded-lg bg-muted/30 p-3">
                <div className="text-xs text-muted-foreground">Bilan paris</div>
                <div className="text-lg font-bold tabular-nums">{data.portefeuille.nb_gagnes}/{data.portefeuille.nb_regles}</div>
                <div className="text-[10px] text-muted-foreground">
                  {data.portefeuille.win_rate == null ? "—" : `${data.portefeuille.win_rate}% réussite`}
                  {data.portefeuille.nb_attente > 0 && ` · ${data.portefeuille.nb_attente} en attente`}
                </div>
              </div>
            </div>

            {/* Répartition par type */}
            {data.par_type.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Par type de pari</h3>
                <div className="flex flex-wrap gap-2">
                  {data.par_type.map((t) => (
                    <div key={t.type_pari} className="rounded-lg border border-border px-3 py-1.5 text-xs">
                      <span className="font-semibold capitalize">{t.type_pari}</span>
                      <span className="text-muted-foreground"> · {t.nb_gagnes}/{t.nb} · </span>
                      <span className={cn("tabular-nums", t.net >= 0 ? "text-green-700" : "text-destructive")}>{t.net >= 0 ? "+" : ""}{formatEuro(t.net)}</span>
                      {t.roi != null && <span className="text-muted-foreground"> ({t.roi >= 0 ? "+" : ""}{t.roi}%)</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Abonnements */}
            {data.subscriptions.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Abonnements</h3>
                <div className="space-y-1">
                  {data.subscriptions.map((s) => (
                    <div key={s.sub_id} className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="secondary" className="text-[10px]">{s.plan}</Badge>
                      <span>{s.periodicite}</span>
                      <span className={cn(s.statut === "active" ? "text-green-700" : "text-muted-foreground")}>· {s.statut}</span>
                      {s.periode_fin && <span>· jusqu&apos;au {formatDateTime(s.periode_fin)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Historique des paris */}
            <div>
              <h3 className="text-sm font-semibold mb-2">Historique des paris ({data.nb_bets})</h3>
              {data.bets.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun pari enregistré.</p>
              ) : (
                <>
                  {/* Mobile : liste de cartes */}
                  <div className="sm:hidden max-h-96 overflow-y-auto space-y-2">
                    {data.bets.map((b) => (
                      <div key={b.entry_id} className="rounded-lg border border-border p-2.5 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium capitalize">
                            {b.type_pari}
                            {b.suivi_reco_ia && <span className="ml-1 text-[9px] text-brand-gold-dark">IA</span>}
                          </span>
                          {resultBadge(b.resultat)}
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground truncate" title={b.chevaux || ""}>{b.chevaux || "—"}</div>
                        <div className="mt-1.5 flex items-center justify-between text-[11px]">
                          <span className="text-muted-foreground">
                            {b.course_code && <span className="font-mono font-semibold text-foreground">{b.course_code} </span>}
                            {formatEuro(b.mise)}{b.cote ? ` · @${b.cote.toFixed(2)}` : ""}
                          </span>
                          <span className={cn("tabular-nums font-semibold", (b.gain_perte ?? 0) > 0 ? "text-green-700" : (b.gain_perte ?? 0) < 0 ? "text-destructive" : "text-muted-foreground")}>
                            {b.gain_perte == null ? "—" : `${b.gain_perte >= 0 ? "+" : ""}${formatEuro(b.gain_perte)}`}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Desktop : tableau complet */}
                  <div className="hidden sm:block max-h-96 overflow-y-auto overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                        <tr className="text-muted-foreground">
                          <th className="text-left p-2">Date</th>
                          <th className="text-left p-2">Course</th>
                          <th className="text-left p-2">Type</th>
                          <th className="text-left p-2">Chevaux</th>
                          <th className="text-right p-2">Mise</th>
                          <th className="text-right p-2">Cote</th>
                          <th className="text-center p-2">Résultat</th>
                          <th className="text-right p-2">Gain/Perte</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.bets.map((b) => (
                          <tr key={b.entry_id} className="border-t border-border/50 hover:bg-muted/20">
                            <td className="p-2 whitespace-nowrap text-muted-foreground">{formatDateTime(b.date)}</td>
                            <td className="p-2 whitespace-nowrap">
                              {b.course_code && <span className="font-mono font-semibold">{b.course_code}</span>}
                              {b.hippodrome && <span className="text-muted-foreground"> {b.hippodrome}</span>}
                            </td>
                            <td className="p-2 capitalize whitespace-nowrap">
                              {b.type_pari}
                              {b.suivi_reco_ia && <span className="ml-1 text-[9px] text-brand-gold-dark" title="Suivi reco IA">IA</span>}
                            </td>
                            <td className="p-2 max-w-[120px] truncate" title={b.chevaux || ""}>{b.chevaux || "—"}</td>
                            <td className="p-2 text-right tabular-nums">{formatEuro(b.mise)}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{b.cote ? b.cote.toFixed(2) : "—"}</td>
                            <td className="p-2 text-center">{resultBadge(b.resultat)}</td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", (b.gain_perte ?? 0) > 0 ? "text-green-700" : (b.gain_perte ?? 0) < 0 ? "text-destructive" : "text-muted-foreground")}>
                              {b.gain_perte == null ? "—" : `${b.gain_perte >= 0 ? "+" : ""}${formatEuro(b.gain_perte)}`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [retraining, setRetraining] = useState(false);
  const [deployingVersion, setDeployingVersion] = useState<number | null>(null);
  // Listes longues : on n'affiche que la tête, le reste à la demande.
  const [toutErreurs, setToutErreurs] = useState(false);
  const [toutModeles, setToutModeles] = useState(false);
  const [toutMouvements, setToutMouvements] = useState(false);

  const { data: dashboard } = useSWR<DashboardData>(
    user?.is_admin ? "/admin-dashboard" : null,
    () => adminApi.dashboard().then((r) => r.data),
    { refreshInterval: 30000 }
  );

  const { data: models, mutate: mutateModels } = useSWR<ModelVersion[]>(
    user?.is_admin ? "/admin-models" : null,
    () => adminApi.models().then((r) => r.data),
    { refreshInterval: 60000 }
  );

  const { data: scraperStatus } = useSWR<ScraperStatus>(
    user?.is_admin ? "/admin-scraper-status" : null,
    () => adminApi.scraperStatus().then((r) => r.data),
    { refreshInterval: 60000 }
  );

  // Erreurs runtime LIVE (exceptions API + scrapers échoués) — refresh 20s.
  const { data: errorsData, mutate: mutateErrors } = useSWR<{ count_24h: number; errors: SystemError[] }>(
    user?.is_admin ? "/admin-errors" : null,
    () => adminApi.errors().then((r) => r.data),
    { refreshInterval: 20000 }
  );

  // Rentabilité RÉELLE par profil (net + ROI) — réservé admin (déplacé du palmarès public).
  const { data: palmares } = useSWR<{
    n: number; n_courses?: number; total_gain?: number; total_benefice?: number;
    profils?: Array<{ profil: string; label: string; nb_courses: number; mise_totale?: number; gain_total?: number; gain_net: number; roi: number | null; paris_gagnes: number; taux_courses_beneficiaires: number | null }>;
    updated_at?: string;
  }>(
    user?.is_admin ? "/admin-palmares-net" : null,
    () => statsApi.palmaresGagnants().then((r) => r.data),
    { refreshInterval: 60000, revalidateOnFocus: true }
  );

  // Suivi des abonnements : essais en cours, cartes manquantes, journal des
  // mouvements. Rafraîchi souvent — c'est la vue que l'exploitant garde ouverte
  // quand un essai approche de sa fin.
  const { data: abos } = useSWR<AbonnementsData>(
    user?.is_admin ? "/admin-abonnements" : null,
    () => adminApi.abonnements().then((r) => r.data),
    { refreshInterval: 30000, revalidateOnFocus: true }
  );

  const [userSearch, setUserSearch] = useState("");
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const { data: users, mutate: mutateUsers } = useSWR(
    user?.is_admin ? ["/admin-users", userSearch] : null,
    () => adminApi.users({ limit: 200, search: userSearch || undefined }).then((r) => r.data),
    { refreshInterval: 30000, revalidateOnFocus: true }
  );

  async function toggleActive(uid: string, current: boolean) {
    try {
      await adminApi.updateUser(uid, { is_active: !current });
      mutateUsers();
    } catch { /* noop */ }
  }
  async function adjustBankroll(uid: string, email: string) {
    const v = window.prompt(`Ajuster le portefeuille de ${email}\nMontant à créditer (+) ou débiter (−), en € :`, "");
    if (v == null) return;
    const m = parseFloat(v.replace(",", "."));
    if (isNaN(m) || m === 0) return;
    try {
      await adminApi.adjustBankroll(uid, m);
      mutateUsers();
    } catch { /* noop */ }
  }
  async function exportUsers() {
    try {
      const res = await adminApi.exportUsers();
      const url = URL.createObjectURL(new Blob([res.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url; a.download = "blackturf_comptes.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch { /* noop */ }
  }

  async function handleRetrain() {
    setRetraining(true);
    try {
      await adminApi.retrain();
      toast.success("Retraining lancé en background");
    } catch {
      toast.error("Erreur lors du déclenchement");
    } finally {
      setRetraining(false);
    }
  }

  async function handleDeploy(version: number) {
    setDeployingVersion(version);
    try {
      await adminApi.deployModel(version);
      toast.success(`Modèle v${version} déployé`);
      mutateModels();
    } catch {
      toast.error("Erreur lors du déploiement");
    } finally {
      setDeployingVersion(null);
    }
  }

  if (authLoading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>;

  if (!user?.is_admin) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <AlertTriangle className="h-12 w-12 text-destructive" />
        <h1 className="text-xl font-bold">Accès refusé</h1>
        <p className="text-muted-foreground">Réservé aux administrateurs BlackTurf.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-3 py-4 sm:space-y-5 sm:px-6 sm:py-7 lg:px-8">
      {/* En-tête collante : le bouton de retrain reste atteignable en bas de page. */}
      <div className="sticky top-0 z-20 -mx-3 flex items-center justify-between gap-2 border-b border-border/60 bg-background/85 px-3 py-2.5 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold sm:text-2xl">Back-office</h1>
          <p className="hidden text-[11px] text-muted-foreground sm:block">
            Actualisation automatique · données live
          </p>
        </div>
        <Button variant="brand" size="sm" onClick={handleRetrain} disabled={retraining}>
          {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          <span className="hidden sm:inline">Retraining manuel</span>
          <span className="sm:hidden">Retrain</span>
        </Button>
      </div>

      {/* Stats */}
      {dashboard && (
        <div className="grid grid-cols-2 gap-2.5 sm:gap-4 md:grid-cols-4">
          <StatCard icon={Users} label="Utilisateurs" value={dashboard.users.total} sub={`+${dashboard.users.nouveaux_7j} cette semaine`} />
          <StatCard icon={CreditCard} label="Abonnés actifs" value={dashboard.users.abonnes_actifs} />
          <StatCard icon={Activity} label="Courses 24h" value={dashboard.courses_24h} />
          <StatCard
            icon={AlertTriangle}
            label="Alertes en erreur"
            value={dashboard.alertes_erreur}
            sub={dashboard.alertes_erreur > 0 ? "à vérifier" : "tout est passé"}
            ton={dashboard.alertes_erreur > 0 ? "alerte" : "neutre"}
          />
        </div>
      )}

      {/* Erreurs runtime LIVE (exceptions API + scrapers échoués) — identifier ce qui casse.
          Repliée par défaut : c'est une pile de détails, pas un indicateur. */}
      {errorsData && errorsData.errors.length > 0 && (() => {
        const nonResolues = errorsData.errors.filter((e) => !e.resolved).length;
        const visibles = toutErreurs ? errorsData.errors : errorsData.errors.slice(0, 8);
        return (
          <AdminSection
            id="erreurs"
            titre="Erreurs récentes"
            sousTitre="Exceptions API et scrapers échoués sur 72 h"
            icone={<AlertTriangle className="h-4 w-4" />}
            ton="alerte"
            defaut={false}
            bodyClassName="p-0 sm:p-0"
            resume={
              <>
                <Puce ton={nonResolues > 0 ? "alerte" : "ok"}>{nonResolues} ouverte{nonResolues > 1 ? "s" : ""}</Puce>
                <Puce>{errorsData.errors.length} sur 72 h</Puce>
              </>
            }
          >
            <div className="divide-y divide-border/50">
              {visibles.map((e, i) => (
                <details key={e.id ?? `s${i}`} className="group px-3 py-2.5 text-xs sm:px-5">
                  <summary className="flex cursor-pointer list-none flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold",
                          e.kind === "scraper" ? "bg-amber-500/15 text-amber-700" : "bg-red-500/15 text-red-700")}>
                          {e.source}
                        </span>
                        {e.endpoint && <span className="truncate font-mono text-[10px] text-muted-foreground">{e.endpoint}</span>}
                        {e.resolved && <span className="text-[10px] font-semibold text-emerald-700">✓ résolu</span>}
                      </span>
                      <span className="mt-1 block break-words font-medium text-foreground">{e.message}</span>
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground sm:text-[11px]">
                      {e.created_at ? depuis(e.created_at) : "—"}
                    </span>
                  </summary>
                  {e.created_at && (
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground">{formatDateTime(e.created_at)}</div>
                  )}
                  {e.detail && (
                    <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/40 p-2 text-[11px]">{e.detail}</pre>
                  )}
                  {e.kind === "api" && e.id != null && !e.resolved && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2 h-7 text-[11px]"
                      onClick={async () => { await adminApi.resolveError(e.id!); mutateErrors(); }}
                    >
                      Marquer résolu
                    </Button>
                  )}
                </details>
              ))}
            </div>
            <div className="px-3 pb-3 sm:px-5">
              <VoirPlus
                total={errorsData.errors.length}
                montres={8}
                tout={toutErreurs}
                onToggle={() => setToutErreurs((v) => !v)}
              />
            </div>
          </AdminSection>
        );
      })()}

      {/* Rentabilité réelle par profil (NET + ROI) — admin only, déplacé du palmarès public.
          Affiche le bénéfice net (peut être négatif) pour suivre l'évolution réelle. */}
      <AdminSection
        id="rentabilite"
        titre="Rentabilité réelle par profil"
        sousTitre="10 €/profil/course, rapports PMU réels — net réel, peut être négatif"
        icone={<Wallet className="h-4 w-4" />}
        ton="or"
        resume={palmares ? (
          <>
            <Puce ton={(palmares.total_benefice ?? 0) >= 0 ? "ok" : "alerte"}>
              {(palmares.total_benefice ?? 0) >= 0 ? "+" : ""}{(palmares.total_benefice ?? 0).toFixed(0)} €
            </Puce>
            <Puce>{palmares.n_courses ?? 0} courses</Puce>
          </>
        ) : undefined}
      >
        <>
          {!palmares ? (
            <div className="py-6 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
          ) : (
            <>
              <div className="mb-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <Tuile
                  label="Bénéfice net total"
                  valeur={`${(palmares.total_benefice ?? 0) >= 0 ? "+" : ""}${(palmares.total_benefice ?? 0).toFixed(0)} €`}
                  ton={(palmares.total_benefice ?? 0) >= 0 ? "ok" : "alerte"}
                />
                <Tuile label="Total gagné" valeur={`${(palmares.total_gain ?? 0).toFixed(0)} €`} ton="ok" />
                <Tuile label="Paris gagnés" valeur={palmares.n} />
                <Tuile label="Courses" valeur={palmares.n_courses ?? 0} />
              </div>
              {palmares.profils && palmares.profils.length > 0 && (
                <>
                  {/* Mobile : cartes par profil */}
                  <div className="sm:hidden space-y-2">
                    {palmares.profils.map((p) => (
                      <div key={p.profil} className="rounded-lg border border-border p-3">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-sm">{PROFIL_NET_LABELS[p.profil] ?? p.label}</span>
                          <span className={cn("text-sm font-bold tabular-nums", p.gain_net >= 0 ? "text-green-700" : "text-destructive")}>
                            {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground tabular-nums">
                          <span>{p.nb_courses} courses</span>
                          <span>misé {(p.mise_totale ?? 0).toFixed(0)}€</span>
                          <span className="text-green-700">gagné {(p.gain_total ?? 0).toFixed(0)}€</span>
                          <span className={cn((p.roi ?? 0) >= 0 ? "text-green-700" : "text-destructive")}>
                            ROI {p.roi != null ? `${p.roi >= 0 ? "+" : ""}${p.roi}%` : "—"}
                          </span>
                          {p.taux_courses_beneficiaires != null && <span>{p.taux_courses_beneficiaires}% courses +</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Desktop : tableau */}
                  <div className="hidden sm:block overflow-x-auto">
                    <table className="w-full text-sm min-w-[560px]">
                      <thead>
                        <tr className="border-b border-border text-xs text-muted-foreground">
                          <th className="text-left p-2 font-medium">Profil</th>
                          <th className="text-right p-2 font-medium">Courses</th>
                          <th className="text-right p-2 font-medium">Misé</th>
                          <th className="text-right p-2 font-medium">Gagné</th>
                          <th className="text-right p-2 font-medium">Net</th>
                          <th className="text-right p-2 font-medium">ROI</th>
                          <th className="text-right p-2 font-medium">% courses +</th>
                        </tr>
                      </thead>
                      <tbody>
                        {palmares.profils.map((p) => (
                          <tr key={p.profil} className="border-b border-border/40">
                            <td className="p-2 font-medium">{PROFIL_NET_LABELS[p.profil] ?? p.label}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{p.nb_courses}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{(p.mise_totale ?? 0).toFixed(0)}€</td>
                            <td className="p-2 text-right tabular-nums text-green-700">{(p.gain_total ?? 0).toFixed(0)}€</td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", p.gain_net >= 0 ? "text-green-700" : "text-destructive")}>
                              {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                            </td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", (p.roi ?? 0) >= 0 ? "text-green-700" : "text-destructive")}>
                              {p.roi != null ? `${p.roi >= 0 ? "+" : ""}${p.roi}%` : "—"}
                            </td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">
                              {p.taux_courses_beneficiaires != null ? `${p.taux_courses_beneficiaires}%` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {palmares.updated_at && (
                <p className="mt-3 text-[11px] text-muted-foreground flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" /> Mis à jour {formatDateTime(palmares.updated_at)} · recalculé à chaque fin de course
                </p>
              )}
            </>
          )}
        </>
      </AdminSection>

      {/* Abonnements — essais, cartes manquantes, journal des mouvements */}
      {abos && (() => {
        // Un échec de paiement coupe l'accès : c'est l'information la plus urgente de
        // la page. Elle ne doit donc jamais dépendre du dépliage du journal — d'où la
        // pastille dans l'en-tête, la ligne d'alerte permanente et l'ouverture d'office.
        const echecsRecents = abos.mouvements
          .filter((m) => MOUVEMENTS_ECHEC.has(m.type)
            && Date.now() - new Date(m.created_at).getTime() < 7 * 86400_000)
          .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
        // Un seul incident écrit DEUX mouvements à quelques secondes d'écart (le statut
        // Stripe `past_due`, puis `paiement_echoue`). Compter les lignes annoncerait
        // deux échecs pour un. On compte les incidents : même compte, moins de 5 min.
        const incidents = echecsRecents.filter((m, i) => !echecsRecents.slice(0, i).some(
          (p) => p.email === m.email
            && Math.abs(+new Date(p.created_at) - +new Date(m.created_at)) < 5 * 60_000,
        ));
        const dernierEchec = echecsRecents[0];
        return (
        <AdminSection
          id="abonnements"
          titre="Abonnements"
          sousTitre="Essais en cours, cartes manquantes, journal des mouvements"
          icone={<CreditCard className="h-4 w-4" />}
          ton={echecsRecents.length > 0 ? "alerte" : "neutre"}
          resume={
            <>
              {echecsRecents.length > 0 && (
                <Puce ton="alerte">
                  {incidents.length} échec{incidents.length > 1 ? "s" : ""} · 7 j
                </Puce>
              )}
              <Puce ton={abos.resume.abonnes_payants > 0 ? "ok" : "neutre"}>
                {abos.resume.abonnes_payants} payant{abos.resume.abonnes_payants > 1 ? "s" : ""}
              </Puce>
              <Puce>{abos.resume.en_essai_avec_carte} en essai</Puce>
              {abos.resume.en_essai_sans_carte > 0 && (
                <Puce ton="attention">{abos.resume.en_essai_sans_carte} sans carte</Puce>
              )}
            </>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
              <Tuile label="Payants" valeur={abos.resume.abonnes_payants} />
              <Tuile label="En essai" valeur={abos.resume.en_essai_avec_carte} />
              <Tuile
                label="Sans carte"
                valeur={abos.resume.en_essai_sans_carte}
                ton={abos.resume.en_essai_sans_carte > 0 ? "attention" : "neutre"}
                sub={abos.resume.en_essai_sans_carte > 0 ? "accès bloqué" : undefined}
              />
              <Tuile
                label="Fin d'essai < 3j"
                valeur={abos.resume.fin_essai_sous_3j}
                ton={abos.resume.fin_essai_sous_3j > 0 ? "attention" : "neutre"}
              />
              <Tuile label="MRR" valeur={formatEuro(abos.resume.mrr)} sub={`ARR ${formatEuro(abos.resume.arr)}`} />
              <Tuile label="Résiliations 30j" valeur={abos.resume.resiliations_30j} />
            </div>

            <p className="rounded-lg border border-border/60 bg-muted/20 p-2.5 text-[11px] leading-relaxed text-muted-foreground">
              Sur 30 jours : {abos.resume.essais_ouverts_30j} essai(s) ouvert(s),{" "}
              {abos.resume.essais_perdus_30j} perdu(s) faute de carte,{" "}
              {abos.resume.resiliations_pendant_essai_30j} résiliation(s) survenue(s)
              pendant l&apos;essai. Un essai perdu n&apos;est pas une résiliation : le
              premier n&apos;a jamais converti, le second était un client.
            </p>

            {abos.abonnes.length > 0 ? (
              <>
                {/* Mobile : une carte par abonnement — le tableau à 5 colonnes déborde. */}
                <div className="space-y-2 sm:hidden">
                  {abos.abonnes.map((a) => (
                    <div key={a.stripe_subscription_id ?? a.user_id} className="rounded-xl border border-border p-3">
                      <div className="flex items-start justify-between gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{a.email}</span>
                        <span className="shrink-0 text-sm font-bold tabular-nums">{formatEuro(a.montant_cents / 100)}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <Badge variant="secondary" className="text-[10px] capitalize">
                          {a.plan}{a.periodicite === "annual" ? " / an" : " / mois"}
                        </Badge>
                        {!a.carte_enregistree ? (
                          <Badge variant="warning" className="text-[10px]">Carte manquante</Badge>
                        ) : a.en_essai ? (
                          <Badge variant="secondary" className="text-[10px]">Essai en cours</Badge>
                        ) : a.acces_ouvert ? (
                          <Badge variant="success" className="text-[10px]">Actif</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-[10px]">{a.statut}</Badge>
                        )}
                      </div>
                      {a.essai_fin && (
                        <div className="mt-1.5 text-[11px] text-muted-foreground">
                          Fin d&apos;essai {formatDateTime(a.essai_fin)}
                          {a.jours_essai_restants !== null && (
                            <span className={cn("ml-1", a.jours_essai_restants <= 3 && "font-semibold text-amber-700")}>
                              (J-{a.jours_essai_restants})
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {/* Desktop : tableau */}
                <div className="hidden overflow-x-auto rounded-xl border border-border/70 sm:block">
                  <table className="w-full text-sm">
                    <thead className="border-b border-border bg-muted/30 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Compte</th>
                        <th className="px-3 py-2 text-left font-medium">Formule</th>
                        <th className="px-3 py-2 text-left font-medium">État</th>
                        <th className="px-3 py-2 text-left font-medium">Fin d&apos;essai</th>
                        <th className="px-3 py-2 text-right font-medium">Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {abos.abonnes.map((a) => (
                        <tr key={a.stripe_subscription_id ?? a.user_id} className="border-b border-border/40 last:border-0 hover:bg-muted/20">
                          <td className="max-w-[240px] truncate px-3 py-2">{a.email}</td>
                          <td className="px-3 py-2 capitalize">
                            {a.plan}
                            <span className="text-xs text-muted-foreground">
                              {a.periodicite === "annual" ? " / an" : " / mois"}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            {!a.carte_enregistree ? (
                              <Badge variant="warning" className="text-[10px]">Carte manquante — accès bloqué</Badge>
                            ) : a.en_essai ? (
                              <Badge variant="secondary" className="text-[10px]">Essai en cours</Badge>
                            ) : a.acces_ouvert ? (
                              <Badge variant="success" className="text-[10px]">Actif</Badge>
                            ) : (
                              <Badge variant="secondary" className="text-[10px]">{a.statut}</Badge>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2">
                            {a.essai_fin ? (
                              <>
                                {formatDateTime(a.essai_fin)}
                                {a.jours_essai_restants !== null && (
                                  <span className={cn("ml-1 text-xs",
                                    a.jours_essai_restants <= 3 ? "text-amber-700 font-semibold" : "text-muted-foreground")}>
                                    (J-{a.jours_essai_restants})
                                  </span>
                                )}
                              </>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                            {formatEuro(a.montant_cents / 100)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Aucun abonnement en cours.</p>
            )}

            {dernierEchec && (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-3 py-2 text-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
                <span className="font-semibold text-destructive">
                  {MOUVEMENT_LABELS[dernierEchec.type] ?? dernierEchec.type}
                </span>
                <span className="max-w-[220px] truncate text-xs sm:text-sm">
                  {dernierEchec.email ?? "compte supprimé"}
                </span>
                <span className="text-xs text-muted-foreground" title={formatDateTime(dernierEchec.created_at)}>
                  {depuis(dernierEchec.created_at)}
                </span>
                {incidents.length > 1 && (
                  <span className="text-xs text-muted-foreground">
                    · {incidents.length - 1} autre{incidents.length > 2 ? "s" : ""} sur 7 j
                  </span>
                )}
              </div>
            )}

            <AdminSection
              id="abonnements-mouvements"
              titre="Derniers mouvements"
              sousTitre="Journal Stripe : essais, cartes, encaissements, résiliations"
              icone={<History className="h-4 w-4" />}
              defaut={echecsRecents.length > 0}
              ton={echecsRecents.length > 0 ? "alerte" : "neutre"}
              resume={
                <>
                  {echecsRecents.length > 0 && <Puce ton="alerte">{incidents.length} échec{incidents.length > 1 ? "s" : ""}</Puce>}
                  <Puce>{abos.mouvements.length}</Puce>
                </>
              }
            >
              {abos.mouvements.length > 0 ? (
                <>
                  <ol className="space-y-1">
                    {(toutMouvements ? abos.mouvements : abos.mouvements.slice(0, 10)).map((m, i, liste) => {
                      const st = TON_MOUVEMENT[MOUVEMENT_TONS[m.type] ?? "secondary"];
                      const libelle = MOUVEMENT_LABELS[m.type] ?? m.type;
                      const montant = montantMouvement(m.montant_cents);
                      const jour = jourMouvement(m.created_at);
                      // Séparateur de journée : le journal mélangeait « il y a 5 h »
                      // et « il y a 7 j » sans repère, on ne voyait plus ce qui
                      // s'était passé aujourd'hui.
                      const nouveauJour = i === 0 || jour !== jourMouvement(liste[i - 1].created_at);
                      return (
                        <li key={m.event_id}>
                          {nouveauJour && (
                            <div className="flex items-center gap-2 px-1 pb-1 pt-3 first:pt-0">
                              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {jour}
                              </span>
                              <span className="h-px flex-1 bg-border" />
                            </div>
                          )}
                          <div className={cn("flex items-start gap-3 rounded-lg border-l-2 py-2 pl-3 pr-2", st.rail, st.fond)}>
                            <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", st.point)} aria-hidden />
                            <div className="min-w-0 flex-1">
                              <div className={cn("text-sm font-semibold leading-snug", st.texte)}>{libelle}</div>
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
                              {montant && (
                                <div className="text-sm font-semibold tabular-nums">{montant}</div>
                              )}
                              <div
                                className="whitespace-nowrap text-[11px] text-muted-foreground"
                                title={formatDateTime(m.created_at)}
                              >
                                {depuis(m.created_at)}
                              </div>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                  <VoirPlus
                    total={abos.mouvements.length}
                    montres={10}
                    tout={toutMouvements}
                    onToggle={() => setToutMouvements((v) => !v)}
                  />
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Aucun mouvement enregistré.</p>
              )}
            </AdminSection>
          </div>
        </AdminSection>
        );
      })()}

      {/* Modèle actif */}
      {dashboard?.modele && (
        <AdminSection
          id="modele-actif"
          titre="Modèle actif"
          sousTitre={dashboard.modele.trained_at ? `Entraîné ${depuis(dashboard.modele.trained_at)}` : "Aucun modèle déployé"}
          icone={<Brain className="h-4 w-4" />}
          resume={dashboard.modele.version ? <Puce ton="ok">v{dashboard.modele.version}</Puce> : <Puce ton="alerte">aucun</Puce>}
        >
          {dashboard.modele.version ? (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <Tuile label="AUC-ROC" valeur={dashboard.modele.auc_roc?.toFixed(4) ?? "—"} />
              <Tuile label="Précision Top-3" valeur={`${((dashboard.modele.precision_top3 || 0) * 100).toFixed(1)} %`} />
              <Tuile
                label="Entraîné le"
                valeur={<span className="text-sm">{formatDateTime(dashboard.modele.trained_at)}</span>}
                sub={depuis(dashboard.modele.trained_at)}
                className="col-span-2 sm:col-span-1"
              />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Aucun modèle déployé.</p>
          )}
        </AdminSection>
      )}

      {/* Versions modèles */}
      {models && models.length > 0 && (() => {
        const actif = models.find((m) => m.est_actif);
        const visibles = toutModeles ? models : models.slice(0, 5);
        return (
        <AdminSection
          id="modeles-historique"
          titre="Historique des modèles"
          sousTitre="Versions entraînées, métriques et redéploiement"
          icone={<History className="h-4 w-4" />}
          defaut={false}
          bodyClassName="p-0 sm:p-0"
          resume={
            <>
              <Puce>{models.length} version{models.length > 1 ? "s" : ""}</Puce>
              {actif && <Puce ton="ok">actif v{actif.version_num}</Puce>}
            </>
          }
        >
          <>
            {/* Mobile : cartes par version */}
            <div className="space-y-2 p-3 sm:hidden">
              {visibles.map((m) => (
                <div key={m.version_num} className={cn("rounded-lg border border-border p-3", m.est_actif && "bg-brand-gold/5 border-brand-gold/30")}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold">v{m.version_num}</span>
                    <div className="flex items-center gap-2">
                      {m.est_actif ? (
                        <Badge variant="success">Actif</Badge>
                      ) : m.est_rollback ? (
                        <Badge variant="warning">Rollback</Badge>
                      ) : (
                        <Badge variant="secondary">Archivé</Badge>
                      )}
                      {!m.est_actif && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleDeploy(m.version_num)}
                          disabled={deployingVersion === m.version_num}
                        >
                          {deployingVersion === m.version_num ? <Loader2 className="h-3 w-3 animate-spin" /> : "Déployer"}
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] tabular-nums">
                    <span className="text-muted-foreground">AUC <span className="text-foreground font-semibold">{m.auc_roc.toFixed(4)}</span></span>
                    <span className="text-muted-foreground">Brier <span className={cn("font-semibold", m.brier_score < 0.18 ? "text-brand-emerald-dark" : "text-brand-red")}>{m.brier_score.toFixed(4)}</span></span>
                    <span className="text-muted-foreground">WF-AUC <span className="text-foreground font-semibold">{m.walk_forward_auc ? m.walk_forward_auc.toFixed(4) : "—"}</span></span>
                    <span className="text-muted-foreground">Top-3 <span className="text-foreground font-semibold">{m.precision_top3 != null ? `${(m.precision_top3 * 100).toFixed(1)}%` : "—"}</span></span>
                    <span className="text-muted-foreground">ROI <span className={cn("font-semibold", (m.roi_simule ?? 0) >= 0 ? "text-brand-emerald-dark" : "text-destructive")}>{m.roi_simule != null ? `${m.roi_simule >= 0 ? "+" : ""}${(m.roi_simule * 100).toFixed(1)}%` : "—"}</span></span>
                    <span className="text-muted-foreground">{m.nb_courses_train.toLocaleString("fr-FR")} partants</span>
                  </div>
                </div>
              ))}
              <div className="px-0">
                <VoirPlus total={models.length} montres={5} tout={toutModeles} onToggle={() => setToutModeles((v) => !v)} />
              </div>
            </div>
            {/* Desktop : tableau */}
            <div className="hidden overflow-x-auto p-3 sm:block sm:p-4">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="text-left p-3">Version</th>
                    <th className="text-right p-3">AUC-ROC</th>
                    <th className="text-right p-3">Brier</th>
                    <th className="text-right p-3">WF-AUC</th>
                    <th className="text-right p-3">Top-3</th>
                    <th className="text-right p-3">ROI sim.</th>
                    <th className="text-right p-3" title="Partants d'entraînement (≈9,3 par course)">Partants</th>
                    <th className="text-center p-3">Statut</th>
                    <th className="text-right p-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((m) => (
                    <tr key={m.version_num} className={cn("border-b border-border/50", m.est_actif && "bg-brand-gold/5")}>
                      <td className="p-3 font-mono font-bold">v{m.version_num}</td>
                      <td className="p-3 text-right">{m.auc_roc.toFixed(4)}</td>
                      <td className={cn("p-3 text-right text-xs", m.brier_score < 0.18 ? "text-brand-emerald-dark" : "text-brand-red")}>
                        {m.brier_score.toFixed(4)}
                      </td>
                      <td className="p-3 text-right text-xs text-muted-foreground">
                        {m.walk_forward_auc ? m.walk_forward_auc.toFixed(4) : "—"}
                      </td>
                      <td className="p-3 text-right">{m.precision_top3 != null ? `${(m.precision_top3 * 100).toFixed(1)}%` : "—"}</td>
                      <td className={cn("p-3 text-right", (m.roi_simule ?? 0) >= 0 ? "text-brand-emerald-dark" : "text-destructive")}>
                        {m.roi_simule != null ? `${m.roi_simule >= 0 ? "+" : ""}${(m.roi_simule * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="p-3 text-right text-muted-foreground tabular-nums">{m.nb_courses_train.toLocaleString("fr-FR")}</td>
                      <td className="p-3 text-center">
                        {m.est_actif ? (
                          <Badge variant="success">Actif</Badge>
                        ) : m.est_rollback ? (
                          <Badge variant="warning">Rollback</Badge>
                        ) : (
                          <Badge variant="secondary">Archivé</Badge>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        {!m.est_actif && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleDeploy(m.version_num)}
                            disabled={deployingVersion === m.version_num}
                          >
                            {deployingVersion === m.version_num ? <Loader2 className="h-3 w-3 animate-spin" /> : "Déployer"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <VoirPlus total={models.length} montres={5} tout={toutModeles} onToggle={() => setToutModeles((v) => !v)} />
            </div>
          </>
        </AdminSection>
        );
      })()}

      {/* Scraper status */}
      {scraperStatus && (() => {
        const sources = Object.entries(scraperStatus);
        // « ok_avec_echecs » (échecs comptés, sous le seuil d'anomalie) reste sain : le
        // traiter en échec ferait clignoter la page pour rien. Liste EXPLICITE et jamais
        // un préfixe « ok » : `sante_scrapers()` produit aussi `ok_but_empty` — que des
        // succès, aucune donnée — et c'est le cas trompeur du projet (4 scrapers « ok »
        // à zéro donnée pendant des semaines). Il doit rester rouge.
        const SAINS = ["ok", "ok_avec_echecs"];
        const sain = (s: string) => SAINS.includes(s);
        const ok = sources.filter(([, s]) => sain(s.statut)).length;
        return (
          <AdminSection
            id="scrapers"
            titre="Scrapers"
            sousTitre="Statut et fraîcheur par source"
            icone={<Radio className="h-4 w-4" />}
            defaut={false}
            ton={ok < sources.length ? "alerte" : "neutre"}
            resume={
              <>
                <Puce ton={ok === sources.length ? "ok" : "alerte"}>{ok}/{sources.length} OK</Puce>
                {ok < sources.length && <Puce ton="alerte">{sources.length - ok} en échec</Puce>}
              </>
            }
          >
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {sources.map(([source, status]) => (
                <div
                  key={source}
                  className={cn(
                    "rounded-xl border p-3",
                    sain(status.statut) ? "border-border bg-muted/10" : "border-destructive/30 bg-destructive/[0.04]",
                  )}
                >
                  <div className="mb-1 flex items-center gap-2">
                    {sain(status.statut) ? (
                      <CheckCircle className={cn("h-4 w-4 shrink-0", status.statut === "ok" ? "text-emerald-600" : "text-amber-600")} />
                    ) : (
                      <XCircle className="h-4 w-4 shrink-0 text-destructive" />
                    )}
                    <span className="truncate text-sm font-semibold capitalize">{source}</span>
                    {sain(status.statut) && status.statut !== "ok" && (
                      <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                        {status.statut}
                      </span>
                    )}
                    {status.duree_ms != null && (
                      <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {status.duree_ms} ms
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3 shrink-0" />
                    <span title={status.derniere_maj ? formatDateTime(status.derniere_maj) : undefined}>
                      {status.derniere_maj ? depuis(status.derniere_maj) : "jamais"}
                    </span>
                  </div>
                  {status.erreur && (
                    <div className="mt-1 break-words text-[11px] text-destructive">{status.erreur}</div>
                  )}
                </div>
              ))}
            </div>
          </AdminSection>
        );
      })()}

      {/* Gestion des comptes */}
      {users && (
        <AdminSection
          id="comptes"
          titre="Comptes"
          sousTitre="Portefeuilles, abonnements et actions par compte"
          icone={<UserCog className="h-4 w-4" />}
          bodyClassName="p-0 sm:p-0"
          resume={<Puce>{(users as unknown[]).length}</Puce>}
          action={
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <input
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Rechercher…"
                className="flex-1 rounded-lg border border-input bg-muted/30 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold/40 sm:w-56 sm:flex-none"
              />
              <button onClick={exportUsers} className="whitespace-nowrap rounded-lg border border-border px-3 py-1.5 text-xs font-semibold transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark">
                ⬇ CSV
              </button>
            </div>
          }
        >
          <>
            {/* Mobile : cartes par compte */}
            <div className="sm:hidden space-y-2 p-3">
              {(users as Array<{
                user_id: string; email: string; nom: string | null; prenom: string | null;
                plan: string; profil_risque: string; is_active: boolean; is_admin: boolean;
                email_verified: boolean; auth_method: string; stripe_client: boolean;
                abonnement_statut: string | null; last_login: string | null;
                created_at: string; solde_actuel: number; mise_totale: number; gain_net: number;
                roi: number | null; nb_paris: number; nb_gagnes: number;
              }>).map((u) => {
                const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || "—";
                return (
                  <div key={u.user_id} className="rounded-lg border border-border p-3">
                    <div className="flex items-start justify-between gap-2">
                      <button
                        onClick={() => setSelectedUser(u.user_id)}
                        className="text-left min-w-0 flex-1"
                        title="Voir l'historique complet">
                        <div className="font-medium flex items-center gap-1.5 truncate">
                          {nom}
                          {u.is_admin && <Badge variant="secondary" className="text-[9px]">ADMIN</Badge>}
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">{u.email}</div>
                      </button>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <Badge variant={u.plan === "expert" ? "expert" : ["starter", "standard"].includes(u.plan) ? "gold" : "secondary"} className="text-[10px]">{u.plan}</Badge>
                        {u.is_active ? <CheckCircle className="h-4 w-4 text-green-700" /> : <XCircle className="h-4 w-4 text-destructive" />}
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] tabular-nums">
                      <span className="font-mono">{u.solde_actuel?.toFixed(0)}€</span>
                      <span className={cn("font-mono font-semibold", u.gain_net >= 0 ? "text-green-700" : "text-destructive")}>{u.gain_net >= 0 ? "+" : ""}{u.gain_net?.toFixed(0)}€</span>
                      <span className={cn("font-mono", u.roi == null ? "text-muted-foreground" : u.roi >= 0 ? "text-green-700" : "text-destructive")}>{u.roi == null ? "—" : `${u.roi >= 0 ? "+" : ""}${u.roi}%`}</span>
                      <span className="text-muted-foreground">{u.nb_gagnes}/{u.nb_paris} paris</span>
                      <span className="text-muted-foreground capitalize">{u.profil_risque}</span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2 flex-wrap text-[11px]">
                      {subBadge(u.abonnement_statut, u.stripe_client)}
                      <span className="text-muted-foreground">Vu {lastLoginLabel(u.last_login)}</span>
                    </div>
                    <div className="mt-2 flex gap-2">
                      <button
                        onClick={() => toggleActive(u.user_id, u.is_active)}
                        className={cn("rounded px-2 py-1 text-[10px] font-semibold border transition-colors",
                          u.is_active ? "border-destructive/40 text-destructive hover:bg-destructive/10" : "border-green-500/40 text-green-700 hover:bg-green-500/10")}>
                        {u.is_active ? "Suspendre" : "Réactiver"}
                      </button>
                      <button
                        onClick={() => adjustBankroll(u.user_id, u.email)}
                        className="rounded px-2 py-1 text-[10px] font-semibold border border-border text-muted-foreground hover:border-brand-gold/50 hover:text-brand-gold-dark transition-colors">
                        💰 Ajuster
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          {/* Desktop : tableau complet */}
          <div className="hidden overflow-x-auto p-3 sm:block sm:p-4">
            {/* 13 colonnes débordaient : « Actions » était coupée au milieu du mot.
                « Profil » et « Statut » sont descendues sous le nom, les quatre
                colonnes de chiffres sont regroupées deux à deux. */}
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="text-left p-3">Utilisateur</th>
                  <th className="text-center p-3">Plan</th>
                  <th className="text-center p-3">Abonnement</th>
                  <th className="text-right p-3">Portefeuille</th>
                  <th className="text-right p-3">Résultat</th>
                  <th className="text-center p-3">Paris</th>
                  <th className="text-right p-3">Activité</th>
                  <th className="text-center p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(users as Array<{
                  user_id: string; email: string; nom: string | null; prenom: string | null;
                  plan: string; profil_risque: string; is_active: boolean; is_admin: boolean;
                  email_verified: boolean; auth_method: string; stripe_client: boolean;
                  abonnement_statut: string | null; last_login: string | null;
                  created_at: string; solde_actuel: number; mise_totale: number; gain_net: number;
                  roi: number | null; nb_paris: number; nb_gagnes: number;
                }>).map((u) => {
                  const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || "—";
                  return (
                  <tr key={u.user_id} className={cn("border-b border-border/50 transition-colors hover:bg-muted/20", !u.is_active && "opacity-55")}>
                    <td className="p-3">
                      <button
                        onClick={() => setSelectedUser(u.user_id)}
                        className="flex items-center gap-1.5 text-left font-medium transition-colors hover:text-brand-gold-dark"
                        title="Voir l'historique complet">
                        {nom}
                        {u.is_admin && <Badge variant="secondary" className="text-[9px]">ADMIN</Badge>}
                        {/* Un compte suspendu se lisait à une coche dans une colonne
                            dédiée, identique pour 21 lignes sur 22. Il se lit
                            maintenant là où il compte : à côté du nom. */}
                        {!u.is_active && <Badge variant="secondary" className="text-[9px] text-destructive">SUSPENDU</Badge>}
                      </button>
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span className="truncate" title={u.email}>{u.email}</span>
                        <span className="text-[9px]" title={u.auth_method === "google" ? "Inscription Google" : "Inscription e-mail"}>{u.auth_method === "google" ? "🔵 G" : "✉"}</span>
                        {u.email_verified ? <span className="text-[9px] text-green-700" title="Adresse confirmée">✓</span> : <span className="text-[9px] text-amber-700" title="Adresse jamais confirmée">⚠</span>}
                        {u.stripe_client && <span className="text-[9px] text-violet-700" title="Client Stripe">💳</span>}
                      </div>
                      <div className="mt-0.5 text-[11px] capitalize text-muted-foreground/70">{u.profil_risque}</div>
                    </td>
                    <td className="p-3 text-center">
                      <Badge variant={u.plan === "expert" ? "expert" : ["starter", "standard"].includes(u.plan) ? "gold" : "secondary"} className="text-[10px]">{u.plan}</Badge>
                    </td>
                    <td className="p-3 text-center">{subBadge(u.abonnement_statut, u.stripe_client)}</td>
                    <td className="p-3 text-right">
                      <div className="font-mono tabular-nums">{u.solde_actuel?.toFixed(0)}€</div>
                      <div className="text-[11px] tabular-nums text-muted-foreground" title="Total misé">
                        {u.mise_totale ? `${u.mise_totale.toFixed(0)}€ misés` : "aucune mise"}
                      </div>
                    </td>
                    <td className="p-3 text-right">
                      <div className={cn("font-mono font-semibold tabular-nums", u.gain_net >= 0 ? "text-green-700" : "text-destructive")}>
                        {u.gain_net >= 0 ? "+" : ""}{u.gain_net?.toFixed(0)}€
                      </div>
                      {/* Un ROI calculé sur un ou deux paris n'apprend rien : « +600 % »
                          sur un seul pari gagné se lisait comme une performance. Il est
                          grisé sous 5 paris pour ne plus être pris au sérieux. */}
                      <div
                        className={cn("text-[11px] tabular-nums",
                          u.roi == null ? "text-muted-foreground"
                            : u.nb_paris < 5 ? "text-muted-foreground/60"
                            : u.roi >= 0 ? "text-green-700" : "text-destructive")}
                        title={u.roi != null && u.nb_paris < 5 ? `ROI sur ${u.nb_paris} pari${u.nb_paris > 1 ? "s" : ""} — non significatif` : "Retour sur investissement"}
                      >
                        {u.roi == null ? "—" : `${u.roi >= 0 ? "+" : ""}${u.roi}%`}
                      </div>
                    </td>
                    <td className="p-3 text-center text-xs tabular-nums">
                      {u.nb_paris === 0 ? <span className="text-muted-foreground">—</span> : `${u.nb_gagnes}/${u.nb_paris}`}
                    </td>
                    <td className="whitespace-nowrap p-3 text-right text-xs text-muted-foreground">
                      <div title="Dernière connexion">{lastLoginLabel(u.last_login)}</div>
                      <div className="text-[11px] text-muted-foreground/70" title="Date d'inscription">inscrit {formatDateTime(u.created_at)}</div>
                    </td>
                    <td className="whitespace-nowrap p-3 text-center">
                      <div className="flex items-center justify-center gap-1.5">
                        <button
                          onClick={() => toggleActive(u.user_id, u.is_active)}
                          className={cn("rounded-md border px-2 py-1 text-[10px] font-semibold transition-colors",
                            u.is_active ? "border-destructive/40 text-destructive hover:bg-destructive/10" : "border-green-500/40 text-green-700 hover:bg-green-500/10")}
                          title={u.is_active ? "Suspendre le compte" : "Réactiver le compte"}>
                          {u.is_active ? "Suspendre" : "Réactiver"}
                        </button>
                        <button
                          onClick={() => adjustBankroll(u.user_id, u.email)}
                          className="rounded-md border border-border px-2 py-1 text-[10px] font-semibold text-muted-foreground transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
                          title="Créditer / débiter le portefeuille">
                          💰 Ajuster
                        </button>
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        </AdminSection>
      )}

      {selectedUser && (
        <UserDetailModal userId={selectedUser} onClose={() => setSelectedUser(null)} />
      )}
    </div>
  );
}
