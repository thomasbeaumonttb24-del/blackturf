"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  Users, Brain, Activity, AlertTriangle, RefreshCw, Loader2,
  CheckCircle, XCircle, Clock, X, Wallet, TrendingUp, CreditCard
} from "lucide-react";

const PROFIL_NET_LABELS: Record<string, string> = {
  conservateur: "Prudent", equilibre: "Modéré", agressif: "Risqué",
};
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  paiement_echoue: "Paiement échoué",
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
};

function StatCard({ icon: Icon, label, value, sub }: { icon: React.ElementType; label: string; value: string | number; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-3 sm:p-5">
        <div className="flex items-center gap-2 sm:gap-3 mb-2">
          <div className="h-8 w-8 sm:h-9 sm:w-9 rounded-lg bg-brand-gold/10 flex items-center justify-center shrink-0">
            <Icon className="h-4 w-4 text-brand-gold" />
          </div>
          <span className="text-xs sm:text-sm text-muted-foreground leading-tight">{label}</span>
        </div>
        <div className="text-xl sm:text-2xl font-bold">{value}</div>
        {sub && <div className="text-[10px] sm:text-xs text-muted-foreground mt-1">{sub}</div>}
      </CardContent>
    </Card>
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
    return <Badge variant="warning" className="text-[10px]">Résilié (fin période)</Badge>;
  if (statut === "past_due")
    return <Badge variant="secondary" className="text-[10px] text-destructive">Paiement échoué</Badge>;
  if (statut === "canceled")
    return <Badge variant="secondary" className="text-[10px] text-muted-foreground">Résilié</Badge>;
  if (statut === "incomplete" || statut === "incomplete_expired")
    return <Badge variant="secondary" className="text-[10px] text-amber-600">Paiement incomplet</Badge>;
  if (stripeClient)
    return <Badge variant="secondary" className="text-[10px] text-muted-foreground" title="Client Stripe créé, jamais d'abonnement finalisé">Checkout abandonné</Badge>;
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
                <div className={cn("text-lg font-bold tabular-nums", data.portefeuille.gain_net >= 0 ? "text-green-600" : "text-destructive")}>
                  {data.portefeuille.gain_net >= 0 ? "+" : ""}{formatEuro(data.portefeuille.gain_net)}
                </div>
                <div className="text-[10px] text-muted-foreground">misé {formatEuro(data.portefeuille.mise_totale)}</div>
              </div>
              <div className="rounded-lg bg-muted/30 p-3">
                <div className="text-xs text-muted-foreground">ROI</div>
                <div className={cn("text-lg font-bold tabular-nums", data.portefeuille.roi == null ? "text-muted-foreground" : data.portefeuille.roi >= 0 ? "text-green-600" : "text-destructive")}>
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
                      <span className={cn("tabular-nums", t.net >= 0 ? "text-green-600" : "text-destructive")}>{t.net >= 0 ? "+" : ""}{formatEuro(t.net)}</span>
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
                      <span className={cn(s.statut === "active" ? "text-green-600" : "text-muted-foreground")}>· {s.statut}</span>
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
                            {b.suivi_reco_ia && <span className="ml-1 text-[9px] text-brand-gold">IA</span>}
                          </span>
                          {resultBadge(b.resultat)}
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground truncate" title={b.chevaux || ""}>{b.chevaux || "—"}</div>
                        <div className="mt-1.5 flex items-center justify-between text-[11px]">
                          <span className="text-muted-foreground">
                            {b.course_code && <span className="font-mono font-semibold text-foreground">{b.course_code} </span>}
                            {formatEuro(b.mise)}{b.cote ? ` · @${b.cote.toFixed(2)}` : ""}
                          </span>
                          <span className={cn("tabular-nums font-semibold", (b.gain_perte ?? 0) > 0 ? "text-green-600" : (b.gain_perte ?? 0) < 0 ? "text-destructive" : "text-muted-foreground")}>
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
                              {b.suivi_reco_ia && <span className="ml-1 text-[9px] text-brand-gold" title="Suivi reco IA">IA</span>}
                            </td>
                            <td className="p-2 max-w-[120px] truncate" title={b.chevaux || ""}>{b.chevaux || "—"}</td>
                            <td className="p-2 text-right tabular-nums">{formatEuro(b.mise)}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{b.cote ? b.cote.toFixed(2) : "—"}</td>
                            <td className="p-2 text-center">{resultBadge(b.resultat)}</td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", (b.gain_perte ?? 0) > 0 ? "text-green-600" : (b.gain_perte ?? 0) < 0 ? "text-destructive" : "text-muted-foreground")}>
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
  async function supprimerCompte(uid: string, email: string) {
    // Confirmation par recopie de l'adresse : un « OK » réflexe ne doit pas
    // suffire à effacer un compte, et la ligne d'à côté a le même bouton.
    const saisie = window.prompt(
      `SUPPRESSION DÉFINITIVE de ${email}\n\n` +
      "Seront effacés : le compte, ses paris, portefeuilles, stratégies et alertes.\n" +
      "Sera conservé : l'historique d'abonnement (pièce comptable), détaché du compte.\n\n" +
      "Recopiez l'adresse e-mail pour confirmer :", "");
    if (saisie == null) return;
    if (saisie.trim().toLowerCase() !== email.toLowerCase()) {
      toast.error("Adresse non conforme — suppression annulée.");
      return;
    }
    try {
      const res = await adminApi.deleteUser(uid);
      const n = (res.data?.supprime ?? {}) as Record<string, number>;
      toast.success(`${email} supprimé — ${n.paris ?? 0} pari(s), ${n.portefeuilles ?? 0} portefeuille(s).`);
      mutateUsers();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Suppression impossible.");
    }
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
    <div className="mx-auto max-w-7xl px-3 sm:px-6 lg:px-8 py-5 sm:py-8 space-y-5 sm:space-y-8">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl sm:text-2xl font-bold">Back-office</h1>
        <Button variant="brand" size="sm" onClick={handleRetrain} disabled={retraining}>
          {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          <span className="hidden sm:inline">Retraining manuel</span>
          <span className="sm:hidden">Retrain</span>
        </Button>
      </div>

      {/* Stats */}
      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard icon={Users} label="Utilisateurs" value={dashboard.users.total} sub={`+${dashboard.users.nouveaux_7j} cette semaine`} />
          <StatCard icon={Users} label="Abonnés actifs" value={dashboard.users.abonnes_actifs} />
          <StatCard icon={Activity} label="Courses 24h" value={dashboard.courses_24h} />
          <StatCard icon={AlertTriangle} label="Alertes en erreur" value={dashboard.alertes_erreur} sub={dashboard.alertes_erreur > 0 ? "⚠ À vérifier" : "✓ OK"} />
        </div>
      )}

      {/* Erreurs runtime LIVE (exceptions API + scrapers échoués) — identifier ce qui casse. */}
      {errorsData && errorsData.errors.length > 0 && (
        <Card className="border-brand-red/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-brand-red" />
              Erreurs récentes
              <span className="text-xs font-normal text-muted-foreground">({errorsData.errors.length} · 72h · live)</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border/50 max-h-[28rem] overflow-auto">
              {errorsData.errors.map((e, i) => (
                <details key={e.id ?? `s${i}`} className="px-4 py-2.5 text-xs">
                  <summary className="cursor-pointer list-none flex items-start justify-between gap-3">
                    <span className="flex-1 min-w-0">
                      <span className="flex items-center gap-2 flex-wrap">
                        <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px]",
                          e.kind === "scraper" ? "bg-amber-500/15 text-amber-700" : "bg-red-500/15 text-red-700")}>
                          {e.source}
                        </span>
                        {e.endpoint && <span className="font-mono text-muted-foreground truncate">{e.endpoint}</span>}
                        {e.resolved && <span className="text-emerald-600 text-[10px]">✓ résolu</span>}
                      </span>
                      <span className="block mt-1 font-medium text-foreground break-words">{e.message}</span>
                    </span>
                    <span className="text-muted-foreground font-mono shrink-0 text-[11px]">
                      {e.created_at ? formatDateTime(e.created_at) : "—"}
                    </span>
                  </summary>
                  {e.detail && (
                    <pre className="mt-2 max-h-60 overflow-auto rounded bg-muted/40 p-2 text-[11px] whitespace-pre-wrap break-words">{e.detail}</pre>
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
          </CardContent>
        </Card>
      )}

      {/* Rentabilité réelle par profil (NET + ROI) — admin only, déplacé du palmarès public.
          Affiche le bénéfice net (peut être négatif) pour suivre l'évolution réelle. */}
      <Card className="border-brand-gold/30">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Wallet className="h-4 w-4 text-brand-gold" /> Rentabilité réelle par profil (net)
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            10€/profil/course, rapports PMU réels. Net réel (peut être négatif), suivi admin.
          </p>
        </CardHeader>
        <CardContent>
          {!palmares ? (
            <div className="py-6 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
                <div className="rounded-lg bg-muted/30 p-3 text-center">
                  <div className="text-xs text-muted-foreground">Bénéfice net total</div>
                  <div className={cn("text-xl font-bold tabular-nums", (palmares.total_benefice ?? 0) >= 0 ? "text-green-600" : "text-destructive")}>
                    {(palmares.total_benefice ?? 0) >= 0 ? "+" : ""}{(palmares.total_benefice ?? 0).toFixed(0)}€
                  </div>
                </div>
                <div className="rounded-lg bg-muted/30 p-3 text-center">
                  <div className="text-xs text-muted-foreground">Total gagné</div>
                  <div className="text-xl font-bold tabular-nums text-green-600">{(palmares.total_gain ?? 0).toFixed(0)}€</div>
                </div>
                <div className="rounded-lg bg-muted/30 p-3 text-center">
                  <div className="text-xs text-muted-foreground">Paris gagnés</div>
                  <div className="text-xl font-bold tabular-nums">{palmares.n}</div>
                </div>
                <div className="rounded-lg bg-muted/30 p-3 text-center">
                  <div className="text-xs text-muted-foreground">Courses</div>
                  <div className="text-xl font-bold tabular-nums">{palmares.n_courses ?? 0}</div>
                </div>
              </div>
              {palmares.profils && palmares.profils.length > 0 && (
                <>
                  {/* Mobile : cartes par profil */}
                  <div className="sm:hidden space-y-2">
                    {palmares.profils.map((p) => (
                      <div key={p.profil} className="rounded-lg border border-border p-3">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-sm">{PROFIL_NET_LABELS[p.profil] ?? p.label}</span>
                          <span className={cn("text-sm font-bold tabular-nums", p.gain_net >= 0 ? "text-green-600" : "text-destructive")}>
                            {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground tabular-nums">
                          <span>{p.nb_courses} courses</span>
                          <span>misé {(p.mise_totale ?? 0).toFixed(0)}€</span>
                          <span className="text-green-600">gagné {(p.gain_total ?? 0).toFixed(0)}€</span>
                          <span className={cn((p.roi ?? 0) >= 0 ? "text-green-600" : "text-destructive")}>
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
                            <td className="p-2 text-right tabular-nums text-green-600">{(p.gain_total ?? 0).toFixed(0)}€</td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", p.gain_net >= 0 ? "text-green-600" : "text-destructive")}>
                              {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                            </td>
                            <td className={cn("p-2 text-right tabular-nums font-semibold", (p.roi ?? 0) >= 0 ? "text-green-600" : "text-destructive")}>
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
                <p className="mt-3 text-[11px] text-muted-foreground/70 flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" /> Mis à jour {formatDateTime(palmares.updated_at)} · recalculé à chaque fin de course
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Abonnements — essais, cartes manquantes, journal des mouvements */}
      {abos && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-brand-gold" /> Abonnements
            </CardTitle>
            {abos.resume.en_essai_sans_carte > 0 && (
              <Badge variant="warning">
                {abos.resume.en_essai_sans_carte} sans carte
              </Badge>
            )}
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
              {[
                { label: "Payants", value: abos.resume.abonnes_payants },
                { label: "En essai", value: abos.resume.en_essai_avec_carte },
                { label: "Sans carte", value: abos.resume.en_essai_sans_carte, alerte: abos.resume.en_essai_sans_carte > 0 },
                { label: "Fin d'essai < 3j", value: abos.resume.fin_essai_sous_3j, alerte: abos.resume.fin_essai_sous_3j > 0 },
                { label: "MRR", value: formatEuro(abos.resume.mrr) },
                { label: "Résiliations 30j", value: abos.resume.resiliations_30j },
              ].map((s) => (
                <div key={s.label} className={cn("text-center p-3 rounded-lg bg-muted/30", s.alerte && "bg-amber-100/60")}>
                  <div className="text-xs text-muted-foreground">{s.label}</div>
                  <div className="text-lg font-bold">{s.value}</div>
                </div>
              ))}
            </div>

            <p className="text-xs text-muted-foreground">
              Sur 30 jours : {abos.resume.essais_ouverts_30j} essai(s) ouvert(s),{" "}
              {abos.resume.essais_perdus_30j} perdu(s) faute de carte,{" "}
              {abos.resume.resiliations_pendant_essai_30j} résiliation(s) survenue(s)
              pendant l&apos;essai. Un essai perdu n&apos;est pas une résiliation : le
              premier n&apos;a jamais converti, le second était un client.
            </p>

            {abos.abonnes.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground border-b border-border">
                    <tr>
                      <th className="text-left py-2 font-medium">Compte</th>
                      <th className="text-left py-2 font-medium">Formule</th>
                      <th className="text-left py-2 font-medium">État</th>
                      <th className="text-left py-2 font-medium">Fin d&apos;essai</th>
                      <th className="text-right py-2 font-medium">Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {abos.abonnes.map((a) => (
                      <tr key={a.stripe_subscription_id ?? a.user_id} className="border-b border-border/50">
                        <td className="py-2 pr-3 truncate max-w-[220px]">{a.email}</td>
                        <td className="py-2 pr-3 capitalize">
                          {a.plan}
                          <span className="text-muted-foreground text-xs">
                            {a.periodicite === "annual" ? " / an" : " / mois"}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
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
                        <td className="py-2 pr-3 whitespace-nowrap">
                          {a.essai_fin ? (
                            <>
                              {formatDateTime(a.essai_fin)}
                              {a.jours_essai_restants !== null && (
                                <span className={cn("ml-1 text-xs",
                                  a.jours_essai_restants <= 3 ? "text-amber-600 font-semibold" : "text-muted-foreground")}>
                                  (J-{a.jours_essai_restants})
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="py-2 text-right whitespace-nowrap">
                          {formatEuro(a.montant_cents / 100)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">Aucun abonnement en cours.</p>
            )}

            <div>
              <h3 className="text-sm font-semibold mb-2">Derniers mouvements</h3>
              {abos.mouvements.length > 0 ? (
                <ul className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
                  {abos.mouvements.map((m) => (
                    <li key={m.event_id} className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge variant={MOUVEMENT_TONS[m.type] ?? "secondary"} className="text-[10px]">
                        {MOUVEMENT_LABELS[m.type] ?? m.type}
                      </Badge>
                      <span className="truncate max-w-[220px]">{m.email ?? "compte supprimé"}</span>
                      {m.plan && (
                        <span className="text-muted-foreground text-xs capitalize">
                          {m.plan_precedent ? `${m.plan_precedent} → ${m.plan}` : m.plan}
                        </span>
                      )}
                      {m.pendant_essai && (
                        <span className="text-xs text-amber-600">pendant l&apos;essai</span>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground whitespace-nowrap">
                        {formatDateTime(m.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-sm">Aucun mouvement enregistré.</p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Modèle actif */}
      {dashboard?.modele && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="h-4 w-4 text-brand-gold" /> Modèle actif
            </CardTitle>
            {dashboard.modele.version && (
              <Badge variant="success">v{dashboard.modele.version}</Badge>
            )}
          </CardHeader>
          <CardContent>
            {dashboard.modele.version ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
                <div className="text-center p-3 rounded-lg bg-muted/30">
                  <div className="text-xs text-muted-foreground">AUC-ROC</div>
                  <div className="text-lg sm:text-xl font-bold">{dashboard.modele.auc_roc?.toFixed(4)}</div>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/30">
                  <div className="text-xs text-muted-foreground">Précision Top-3</div>
                  <div className="text-lg sm:text-xl font-bold">{((dashboard.modele.precision_top3 || 0) * 100).toFixed(1)}%</div>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/30 col-span-2 sm:col-span-1">
                  <div className="text-xs text-muted-foreground">Entraîné le</div>
                  <div className="text-sm font-bold">{formatDateTime(dashboard.modele.trained_at)}</div>
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">Aucun modèle déployé.</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Versions modèles */}
      {models && models.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Historique des modèles</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {/* Mobile : cartes par version */}
            <div className="sm:hidden space-y-2 p-3">
              {models.map((m) => (
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
                    <span className="text-muted-foreground">Brier <span className={cn("font-semibold", m.brier_score < 0.18 ? "text-brand-emerald" : "text-brand-red")}>{m.brier_score.toFixed(4)}</span></span>
                    <span className="text-muted-foreground">WF-AUC <span className="text-foreground font-semibold">{m.walk_forward_auc ? m.walk_forward_auc.toFixed(4) : "—"}</span></span>
                    <span className="text-muted-foreground">Top-3 <span className="text-foreground font-semibold">{m.precision_top3 != null ? `${(m.precision_top3 * 100).toFixed(1)}%` : "—"}</span></span>
                    <span className="text-muted-foreground">ROI <span className={cn("font-semibold", (m.roi_simule ?? 0) >= 0 ? "text-brand-emerald" : "text-destructive")}>{m.roi_simule != null ? `${m.roi_simule >= 0 ? "+" : ""}${(m.roi_simule * 100).toFixed(1)}%` : "—"}</span></span>
                    <span className="text-muted-foreground">{m.nb_courses_train} courses</span>
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop : tableau */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm min-w-[480px]">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="text-left p-3">Version</th>
                    <th className="text-right p-3">AUC-ROC</th>
                    <th className="text-right p-3">Brier</th>
                    <th className="text-right p-3">WF-AUC</th>
                    <th className="text-right p-3">Top-3</th>
                    <th className="text-right p-3">ROI sim.</th>
                    <th className="text-right p-3">Courses</th>
                    <th className="text-center p-3">Statut</th>
                    <th className="text-right p-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.version_num} className={cn("border-b border-border/50", m.est_actif && "bg-brand-gold/5")}>
                      <td className="p-3 font-mono font-bold">v{m.version_num}</td>
                      <td className="p-3 text-right">{m.auc_roc.toFixed(4)}</td>
                      <td className={cn("p-3 text-right text-xs", m.brier_score < 0.18 ? "text-brand-emerald" : "text-brand-red")}>
                        {m.brier_score.toFixed(4)}
                      </td>
                      <td className="p-3 text-right text-xs text-muted-foreground">
                        {m.walk_forward_auc ? m.walk_forward_auc.toFixed(4) : "—"}
                      </td>
                      <td className="p-3 text-right">{m.precision_top3 != null ? `${(m.precision_top3 * 100).toFixed(1)}%` : "—"}</td>
                      <td className={cn("p-3 text-right", (m.roi_simule ?? 0) >= 0 ? "text-brand-emerald" : "text-destructive")}>
                        {m.roi_simule != null ? `${m.roi_simule >= 0 ? "+" : ""}${(m.roi_simule * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="p-3 text-right text-muted-foreground">{m.nb_courses_train}</td>
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
            </div>
          </CardContent>
        </Card>
      )}

      {/* Scraper status */}
      {scraperStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" /> Scraper — Statut par source
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(scraperStatus).map(([source, status]) => (
                <div key={source} className="rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2 mb-1">
                    {status.statut === "ok" ? (
                      <CheckCircle className="h-4 w-4 text-green-600" />
                    ) : (
                      <XCircle className="h-4 w-4 text-destructive" />
                    )}
                    <span className="font-semibold capitalize">{source}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {status.derniere_maj ? formatDateTime(status.derniere_maj) : "Jamais"}
                    </div>
                    {status.duree_ms && <div>{status.duree_ms}ms</div>}
                    {status.erreur && <div className="text-destructive truncate">{status.erreur}</div>}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Gestion des comptes */}
      {users && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2 sm:gap-3">
              <CardTitle className="text-base">Comptes ({(users as unknown[]).length})</CardTitle>
              <div className="flex items-center gap-2 w-full sm:w-auto">
                <input
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  placeholder="Rechercher…"
                  className="rounded-lg border border-input bg-muted/30 px-3 py-1.5 text-sm flex-1 sm:w-56 sm:flex-none focus:outline-none focus:ring-2 focus:ring-brand-gold/40"
                />
                <button onClick={exportUsers} className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold hover:border-brand-gold/50 hover:text-brand-gold transition-colors whitespace-nowrap">
                  ⬇ CSV
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
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
                        {u.is_active ? <CheckCircle className="h-4 w-4 text-green-600" /> : <XCircle className="h-4 w-4 text-destructive" />}
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] tabular-nums">
                      <span className="font-mono">{u.solde_actuel?.toFixed(0)}€</span>
                      <span className={cn("font-mono font-semibold", u.gain_net >= 0 ? "text-green-600" : "text-destructive")}>{u.gain_net >= 0 ? "+" : ""}{u.gain_net?.toFixed(0)}€</span>
                      <span className={cn("font-mono", u.roi == null ? "text-muted-foreground" : u.roi >= 0 ? "text-green-600" : "text-destructive")}>{u.roi == null ? "—" : `${u.roi >= 0 ? "+" : ""}${u.roi}%`}</span>
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
                          u.is_active ? "border-destructive/40 text-destructive hover:bg-destructive/10" : "border-green-500/40 text-green-600 hover:bg-green-500/10")}>
                        {u.is_active ? "Suspendre" : "Réactiver"}
                      </button>
                      <button
                        onClick={() => adjustBankroll(u.user_id, u.email)}
                        className="rounded px-2 py-1 text-[10px] font-semibold border border-border text-muted-foreground hover:border-brand-gold/50 hover:text-brand-gold transition-colors">
                        💰 Ajuster
                      </button>
                      <button
                        onClick={() => supprimerCompte(u.user_id, u.email)}
                        className="rounded px-2 py-1 text-[10px] font-semibold border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors">
                        🗑 Supprimer
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          {/* Desktop : tableau complet */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm min-w-[1120px]">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="text-left p-3">Utilisateur</th>
                  <th className="text-center p-3">Plan</th>
                  <th className="text-center p-3">Profil</th>
                  <th className="text-right p-3">Solde</th>
                  <th className="text-right p-3">Misé</th>
                  <th className="text-right p-3">Net</th>
                  <th className="text-right p-3">ROI</th>
                  <th className="text-center p-3">Paris</th>
                  <th className="text-center p-3">Statut</th>
                  <th className="text-center p-3">Abonnement</th>
                  <th className="text-right p-3">Dernière connexion</th>
                  <th className="text-right p-3">Inscrit le</th>
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
                  <tr key={u.user_id} className="border-b border-border/50 hover:bg-muted/20">
                    <td className="p-3">
                      <button
                        onClick={() => setSelectedUser(u.user_id)}
                        className="font-medium flex items-center gap-1.5 text-left hover:text-brand-gold transition-colors"
                        title="Voir l'historique complet">
                        {nom}
                        {u.is_admin && <Badge variant="secondary" className="text-[9px]">ADMIN</Badge>}
                      </button>
                      <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                        {u.email}
                        <span className="text-[9px]" title={u.auth_method === "google" ? "Google" : "Email"}>{u.auth_method === "google" ? "🔵 G" : "✉"}</span>
                        {u.email_verified ? <span className="text-[9px] text-green-600" title="Email vérifié">✓</span> : <span className="text-[9px] text-amber-500" title="Non vérifié">⚠</span>}
                        {u.stripe_client && <span className="text-[9px] text-violet-500" title="Client Stripe">💳</span>}
                      </div>
                    </td>
                    <td className="p-3 text-center">
                      <Badge variant={u.plan === "expert" ? "expert" : ["starter", "standard"].includes(u.plan) ? "gold" : "secondary"} className="text-[10px]">{u.plan}</Badge>
                    </td>
                    <td className="p-3 text-center text-xs text-muted-foreground capitalize">{u.profil_risque}</td>
                    <td className="p-3 text-right font-mono tabular-nums">{u.solde_actuel?.toFixed(0)}€</td>
                    <td className="p-3 text-right font-mono tabular-nums text-muted-foreground">{u.mise_totale?.toFixed(0)}€</td>
                    <td className={cn("p-3 text-right font-mono tabular-nums font-semibold", u.gain_net >= 0 ? "text-green-600" : "text-destructive")}>{u.gain_net >= 0 ? "+" : ""}{u.gain_net?.toFixed(0)}€</td>
                    <td className={cn("p-3 text-right font-mono tabular-nums", u.roi == null ? "text-muted-foreground" : u.roi >= 0 ? "text-green-600" : "text-destructive")}>{u.roi == null ? "—" : `${u.roi >= 0 ? "+" : ""}${u.roi}%`}</td>
                    <td className="p-3 text-center text-xs tabular-nums">{u.nb_gagnes}/{u.nb_paris}</td>
                    <td className="p-3 text-center">{u.is_active ? <CheckCircle className="h-4 w-4 text-green-600 mx-auto" /> : <XCircle className="h-4 w-4 text-destructive mx-auto" />}</td>
                    <td className="p-3 text-center">{subBadge(u.abonnement_statut, u.stripe_client)}</td>
                    <td className="p-3 text-right text-muted-foreground text-xs whitespace-nowrap">{lastLoginLabel(u.last_login)}</td>
                    <td className="p-3 text-right text-muted-foreground text-xs">{formatDateTime(u.created_at)}</td>
                    <td className="p-3 text-center whitespace-nowrap">
                      <button
                        onClick={() => toggleActive(u.user_id, u.is_active)}
                        className={cn("rounded px-2 py-1 text-[10px] font-semibold border transition-colors mr-1",
                          u.is_active ? "border-destructive/40 text-destructive hover:bg-destructive/10" : "border-green-500/40 text-green-600 hover:bg-green-500/10")}
                        title={u.is_active ? "Suspendre le compte" : "Réactiver le compte"}>
                        {u.is_active ? "Suspendre" : "Réactiver"}
                      </button>
                      <button
                        onClick={() => adjustBankroll(u.user_id, u.email)}
                        className="rounded px-2 py-1 text-[10px] font-semibold border border-border text-muted-foreground hover:border-brand-gold/50 hover:text-brand-gold transition-colors"
                        title="Créditer / débiter le portefeuille">
                        💰 Ajuster
                      </button>
                      <button
                        onClick={() => supprimerCompte(u.user_id, u.email)}
                        className="rounded px-2 py-1 text-[10px] font-semibold border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors ml-1"
                        title="Supprimer définitivement le compte">
                        🗑 Supprimer
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </CardContent>
        </Card>
      )}

      {selectedUser && (
        <UserDetailModal userId={selectedUser} onClose={() => setSelectedUser(null)} />
      )}
    </div>
  );
}
