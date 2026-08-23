"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  Instagram, Loader2, CheckCircle2, AlertTriangle, RefreshCw, Trash2, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

/**
 * Dépôt du jeton Instagram.
 *
 * Cet écran existe pour une raison simple : un jeton d'accès ne doit transiter ni par un
 * chat, ni par un historique de shell, et l'exploitant n'a pas à savoir se connecter en
 * SSH pour faire vivre son produit. Le jeton part d'ici vers le serveur sur une connexion
 * chiffrée, et n'en ressort jamais — l'API ne renvoie que son état.
 */

interface EtatJeton {
  configure: boolean;
  compte_id?: string | null;
  expire_at?: string | null;
  jours_restants?: number | null;
  dernier_renouvellement_at?: string | null;
  derniere_erreur?: string | null;
  depose_le?: string | null;
}

const LIEN_META =
  "https://developers.facebook.com/apps/1798925871293047/use_cases/customize/API-Setup/?product_route=instagram-business&use_case_enum=INSTAGRAM_BUSINESS&selected_tab=API-Setup";

export default function AdminInstagramPage() {
  const { user, loading } = useRequireAuth();
  const [jeton, setJeton] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [action, setAction] = useState<null | "renouveler" | "tester">(null);

  const { data: etat, mutate } = useSWR<EtatJeton>(
    user?.is_admin ? "/admin/integrations/instagram" : null,
    () => api.get("/admin/integrations/instagram").then((r) => r.data),
  );

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-gold" />
      </div>
    );
  }
  if (!user?.is_admin) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center text-sm text-muted-foreground">
        Accès réservé à l&apos;administration.
      </div>
    );
  }

  async function deposer(e: React.FormEvent) {
    e.preventDefault();
    const valeur = jeton.trim();
    if (valeur.length < 50) {
      toast.error("Le jeton semble tronqué — recopiez-le en entier.");
      return;
    }
    setEnvoi(true);
    try {
      const r = await api.post("/admin/integrations/instagram", { jeton: valeur });
      // On efface tout de suite le champ : laisser un secret dans un formulaire ouvert,
      // c'est l'exposer à la première capture d'écran.
      setJeton("");
      toast.success(
        r.data?.compte_id
          ? `Jeton enregistré pour le compte ${r.data.compte_id}.`
          : "Jeton enregistré.",
      );
      mutate();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Le jeton n'a pas été accepté.");
    } finally {
      setEnvoi(false);
    }
  }

  async function lancer(quoi: "renouveler" | "tester") {
    setAction(quoi);
    try {
      const r = await api.post(`/admin/integrations/instagram/${quoi}`);
      if (r.data?.ok) {
        toast.success(
          quoi === "tester"
            ? `Connexion établie avec @${r.data.username ?? "?"}.`
            : "Jeton prolongé de 60 jours.",
        );
      } else {
        toast.error(r.data?.raison || r.data?.detail || "Échec.");
      }
      mutate();
    } catch {
      toast.error("Opération impossible.");
    } finally {
      setAction(null);
    }
  }

  async function retirer() {
    if (!confirm("Retirer le jeton ? La publication automatique s'arrêtera.")) return;
    try {
      await api.delete("/admin/integrations/instagram");
      toast.success("Jeton retiré.");
      mutate();
    } catch {
      toast.error("Suppression impossible.");
    }
  }

  const alerte =
    etat?.configure && typeof etat.jours_restants === "number" && etat.jours_restants < 10;

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <div className="mb-8 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-100 to-white ring-1 ring-amber-200">
          <Instagram className="h-5 w-5 text-brand-gold-deep" aria-hidden="true" />
        </span>
        <div>
          <h1 className="font-display text-2xl font-bold text-gray-900">Publication Instagram</h1>
          <p className="text-sm text-muted-foreground">
            Le jeton vit sur le serveur et se renouvelle tout seul. Il n&apos;est jamais
            réaffiché.
          </p>
        </div>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">État de la connexion</CardTitle>
        </CardHeader>
        <CardContent>
          {!etat ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : etat.configure ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Jeton enregistré
              </div>
              <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Compte</dt>
                  <dd className="font-mono text-[13px]">{etat.compte_id ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Expire le</dt>
                  <dd className={alerte ? "font-semibold text-red-600" : ""}>
                    {etat.expire_at ? formatDateTime(etat.expire_at) : "—"}
                    {typeof etat.jours_restants === "number" && (
                      <span className="ml-1 text-muted-foreground">
                        ({etat.jours_restants} j)
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Dernier renouvellement</dt>
                  <dd>
                    {etat.dernier_renouvellement_at
                      ? formatDateTime(etat.dernier_renouvellement_at)
                      : "aucun"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Déposé le</dt>
                  <dd>{etat.depose_le ? formatDateTime(etat.depose_le) : "—"}</dd>
                </div>
              </dl>

              {etat.derniere_erreur && (
                <p className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-800">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>
                    Dernière erreur : {etat.derniere_erreur}
                  </span>
                </p>
              )}

              <div className="flex flex-wrap gap-2 pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => lancer("tester")}
                  disabled={action !== null}
                >
                  {action === "tester" ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Tester la connexion
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => lancer("renouveler")}
                  disabled={action !== null}
                >
                  {action === "renouveler" ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  Renouveler maintenant
                </Button>
                <Button variant="outline" size="sm" onClick={retirer}>
                  <Trash2 className="mr-2 h-3.5 w-3.5" aria-hidden="true" /> Retirer
                </Button>
              </div>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-sm text-amber-800">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              Aucun jeton enregistré — la publication automatique est à l&apos;arrêt.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {etat?.configure ? "Remplacer le jeton" : "Déposer le jeton"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="mb-5 space-y-2 text-sm text-muted-foreground">
            <li>
              <strong className="text-foreground">1.</strong> Ouvrez la{" "}
              <a
                href={LIEN_META}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-medium text-brand-gold-deep hover:underline"
              >
                configuration Instagram de l&apos;app
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
              .
            </li>
            <li>
              <strong className="text-foreground">2.</strong> Section « Générez des tokens
              d&apos;accès », à côté de <code>blackturf.fr</code> : cliquez{" "}
              <strong className="text-foreground">Générer un token</strong>, puis copiez-le.
            </li>
            <li>
              <strong className="text-foreground">3.</strong> Collez-le ci-dessous. Il part
              directement sur le serveur et n&apos;est plus jamais affiché.
            </li>
          </ol>

          <form onSubmit={deposer} className="space-y-3">
            <label htmlFor="jeton" className="sr-only">
              Jeton d&apos;accès Instagram
            </label>
            <textarea
              id="jeton"
              value={jeton}
              onChange={(e) => setJeton(e.target.value)}
              rows={3}
              spellCheck={false}
              autoComplete="off"
              placeholder="Collez ici le jeton généré par Meta…"
              className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-[13px] outline-none focus:ring-2 focus:ring-ring"
            />
            <div className="flex items-center gap-3">
              <Button type="submit" variant="brand" disabled={envoi || jeton.trim().length < 50}>
                {envoi ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Enregistrer le jeton
              </Button>
              <span className="text-xs text-muted-foreground">
                Vérifié auprès d&apos;Instagram avant d&apos;être enregistré.
              </span>
            </div>
          </form>
        </CardContent>
      </Card>

      <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
        Le jeton se renouvelle automatiquement chaque nuit dès qu&apos;il approche de son
        échéance — un jeton Instagram expire au bout de 60 jours, et sans ce renouvellement
        la publication s&apos;arrêterait sans prévenir. Enregistrer un jeton n&apos;active
        aucune publication : celle-ci reste commandée par un réglage distinct, côté serveur.
      </p>
    </div>
  );
}
