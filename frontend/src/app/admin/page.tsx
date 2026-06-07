"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  Users, Brain, Activity, AlertTriangle, RefreshCw, Loader2,
  CheckCircle, XCircle, Clock
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useRequireAuth } from "@/hooks/useAuth";
import { adminApi } from "@/lib/api";
import { formatDateTime, cn } from "@/lib/utils";

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
  precision_top3: number;
  roi_simule: number;
  walk_forward_auc: number | null;
  walk_forward_variance: number | null;
  nb_courses_train: number;
  est_actif: boolean;
  est_rollback: boolean;
  created_at: string;
}

interface ScraperStatus {
  [source: string]: { statut: string; derniere_maj: string | null; duree_ms: number | null; erreur: string | null };
}

function StatCard({ icon: Icon, label, value, sub }: { icon: React.ElementType; label: string; value: string | number; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center gap-3 mb-2">
          <div className="h-9 w-9 rounded-lg bg-brand-gold/10 flex items-center justify-center">
            <Icon className="h-4 w-4 text-brand-gold" />
          </div>
          <span className="text-sm text-muted-foreground">{label}</span>
        </div>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
      </CardContent>
    </Card>
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
    () => adminApi.models().then((r) => r.data)
  );

  const { data: scraperStatus } = useSWR<ScraperStatus>(
    user?.is_admin ? "/admin-scraper-status" : null,
    () => adminApi.scraperStatus().then((r) => r.data),
    { refreshInterval: 60000 }
  );

  const { data: users } = useSWR(
    user?.is_admin ? "/admin-users" : null,
    () => adminApi.users({ limit: 20 }).then((r) => r.data)
  );

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
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Back-office</h1>
        <Button variant="brand" size="sm" onClick={handleRetrain} disabled={retraining}>
          {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Retraining manuel
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
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-3 rounded-lg bg-muted/30">
                  <div className="text-xs text-muted-foreground">AUC-ROC</div>
                  <div className="text-xl font-bold">{dashboard.modele.auc_roc?.toFixed(4)}</div>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/30">
                  <div className="text-xs text-muted-foreground">Précision Top-3</div>
                  <div className="text-xl font-bold">{((dashboard.modele.precision_top3 || 0) * 100).toFixed(1)}%</div>
                </div>
                <div className="text-center p-3 rounded-lg bg-muted/30">
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
          <CardContent className="p-0 overflow-x-auto">
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
                    <td className="p-3 text-right">{(m.precision_top3 * 100).toFixed(1)}%</td>
                    <td className={cn("p-3 text-right", m.roi_simule >= 0 ? "text-brand-emerald" : "text-destructive")}>
                      {m.roi_simule >= 0 ? "+" : ""}{(m.roi_simule * 100).toFixed(1)}%
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
                      <CheckCircle className="h-4 w-4 text-green-400" />
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

      {/* Users */}
      {users && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Derniers utilisateurs</CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-sm min-w-[480px]">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="text-left p-3">Email</th>
                  <th className="text-center p-3">Plan</th>
                  <th className="text-center p-3">Actif</th>
                  <th className="text-right p-3">Inscrit le</th>
                </tr>
              </thead>
              <tbody>
                {(users as Array<{ user_id: string; email: string; plan: string; is_active: boolean; created_at: string }>).map((u) => (
                  <tr key={u.user_id} className="border-b border-border/50">
                    <td className="p-3">{u.email}</td>
                    <td className="p-3 text-center">
                      <Badge variant={["pro", "expert"].includes(u.plan) ? "expert" : ["starter", "standard"].includes(u.plan) ? "gold" : "secondary"} className="text-[10px]">
                        {u.plan}
                      </Badge>
                    </td>
                    <td className="p-3 text-center">
                      {u.is_active ? (
                        <CheckCircle className="h-4 w-4 text-green-400 mx-auto" />
                      ) : (
                        <XCircle className="h-4 w-4 text-destructive mx-auto" />
                      )}
                    </td>
                    <td className="p-3 text-right text-muted-foreground text-xs">{formatDateTime(u.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
