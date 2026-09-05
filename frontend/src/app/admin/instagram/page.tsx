"use client";

/**
 * Dépôt du jeton Instagram.
 *
 * Cet écran existe pour une raison simple : un jeton d'accès ne doit transiter ni par un
 * chat, ni par un historique de shell, et l'exploitant n'a pas à savoir se connecter en
 * SSH pour faire vivre son produit. Le jeton part d'ici vers le serveur sur une connexion
 * chiffrée, et n'en ressort jamais — l'API ne renvoie que son état.
 *
 * Refonte visuelle : la page utilisait les `Card` du site public, donc un troisième
 * langage visuel dans une console qui en avait déjà deux. Elle emprunte maintenant les
 * mêmes panneaux que le reste de l'administration, et la mode d'emploi passe en trois
 * étapes numérotées au lieu d'une liste à puces où le lien Meta se perdait.
 */

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ExternalLink, Instagram, Loader2,
  RefreshCw, Trash2,
} from "lucide-react";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import { EnTetePage, Encart, GrilleTuiles, Panneau, Squelette, Tuile } from "@/components/admin/ui";

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

/** En dessous, le renouvellement automatique n'a plus beaucoup de marge : un
 *  échec deux nuits de suite et la publication s'arrête sans prévenir. */
const SEUIL_ALERTE_JOURS = 10;

export default function AdminInstagramPage() {
  const [jeton, setJeton] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [action, setAction] = useState<null | "renouveler" | "tester">(null);

  const { data: etat, mutate } = useSWR<EtatJeton>(
    "/admin/integrations/instagram",
    () => adminApi.integrationInstagram().then((r) => r.data),
  );

  async function deposer(e: React.FormEvent) {
    e.preventDefault();
    const valeur = jeton.trim();
    if (valeur.length < 50) {
      toast.error("Le jeton semble tronqué — recopiez-le en entier.");
      return;
    }
    setEnvoi(true);
    try {
      const r = await adminApi.deposerJetonInstagram(valeur);
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
      const r = await adminApi.actionJetonInstagram(quoi);
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
    if (!window.confirm("Retirer le jeton ? La publication automatique s'arrêtera.")) return;
    try {
      await adminApi.supprimerJetonInstagram();
      toast.success("Jeton retiré.");
      mutate();
    } catch {
      toast.error("Suppression impossible.");
    }
  }

  const alerte = etat?.configure
    && typeof etat.jours_restants === "number"
    && etat.jours_restants < SEUIL_ALERTE_JOURS;

  return (
    <div className="mx-auto max-w-3xl space-y-4 sm:space-y-5">
      <Link
        href="/admin/systeme"
        className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Système · Intégrations
      </Link>

      <EnTetePage
        titre="Publication Instagram"
        icone={<Instagram className="h-4 w-4" />}
        desc="Le jeton vit sur le serveur et se renouvelle tout seul. Il n'est jamais réaffiché — l'API ne renvoie que son état."
      />

      <Panneau
        titre="État de la connexion"
        ton={etat?.configure ? (alerte ? "attention" : "ok") : "attention"}
      >
        {!etat ? (
          <Squelette lignes={3} />
        ) : !etat.configure ? (
          <Encart ton="attention" icone={<AlertTriangle className="h-4 w-4" />}>
            Aucun jeton enregistré — la publication automatique est à l&apos;arrêt.
          </Encart>
        ) : (
          <div className="space-y-4">
            <p className="flex items-center gap-2 text-[13px] font-semibold text-emerald-700">
              <CheckCircle2 className="h-4 w-4" aria-hidden /> Jeton enregistré
            </p>

            <GrilleTuiles colonnes={4}>
              <Tuile
                label="Compte"
                valeur={<span className="font-mono text-base">{etat.compte_id ?? "—"}</span>}
              />
              <Tuile
                label="Expire le"
                valeur={
                  <span className="text-base">
                    {etat.expire_at ? formatDateTime(etat.expire_at) : "—"}
                  </span>
                }
                sub={typeof etat.jours_restants === "number" ? `dans ${etat.jours_restants} jour(s)` : undefined}
                ton={alerte ? "alerte" : "neutre"}
              />
              <Tuile
                label="Dernier renouvellement"
                valeur={
                  <span className="text-base">
                    {etat.dernier_renouvellement_at ? formatDateTime(etat.dernier_renouvellement_at) : "aucun"}
                  </span>
                }
              />
              <Tuile
                label="Déposé le"
                valeur={<span className="text-base">{etat.depose_le ? formatDateTime(etat.depose_le) : "—"}</span>}
              />
            </GrilleTuiles>

            {etat.derniere_erreur && (
              <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
                Dernière erreur : {etat.derniere_erreur}
              </Encart>
            )}

            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => lancer("tester")} disabled={action !== null} className="min-h-[2.75rem]">
                {action === "tester" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Tester la connexion
              </Button>
              <Button variant="outline" onClick={() => lancer("renouveler")} disabled={action !== null} className="min-h-[2.75rem]">
                {action === "renouveler"
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <RefreshCw className="h-4 w-4" aria-hidden />}
                Renouveler maintenant
              </Button>
              <Button variant="outline" onClick={retirer} className="min-h-[2.75rem] text-destructive hover:text-destructive">
                <Trash2 className="h-4 w-4" aria-hidden /> Retirer
              </Button>
            </div>
          </div>
        )}
      </Panneau>

      <Panneau titre={etat?.configure ? "Remplacer le jeton" : "Déposer le jeton"}>
        <ol className="mb-5 space-y-3">
          {[
            <>
              Ouvrez la{" "}
              <a
                href={LIEN_META}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-brand-gold-dark underline-offset-2 hover:underline"
              >
                configuration Instagram de l&apos;app
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
              .
            </>,
            <>
              Section « Générez des tokens d&apos;accès », à côté de{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">blackturf.fr</code> :
              cliquez <b className="font-semibold text-foreground">Générer un token</b>, puis copiez-le.
            </>,
            <>
              Collez-le ci-dessous. Il part directement sur le serveur et n&apos;est plus jamais
              affiché.
            </>,
          ].map((texte, i) => (
            <li key={i} className="flex gap-3 text-[13px] leading-relaxed text-muted-foreground">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-bold text-foreground">
                {i + 1}
              </span>
              <span className="min-w-0 pt-0.5">{texte}</span>
            </li>
          ))}
        </ol>

        <form onSubmit={deposer} className="space-y-3">
          <label htmlFor="jeton" className="block text-[13px] font-semibold">
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
            className={cn(
              "w-full resize-none rounded-xl border border-input bg-background px-3 py-2.5 font-mono text-base outline-none focus:ring-2 focus:ring-ring sm:text-[13px]",
            )}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              variant="brand"
              disabled={envoi || jeton.trim().length < 50}
              className="min-h-[2.75rem]"
            >
              {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer le jeton
            </Button>
            <span className="text-xs text-muted-foreground">
              Vérifié auprès d&apos;Instagram avant d&apos;être enregistré.
            </span>
          </div>
        </form>
      </Panneau>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Le jeton se renouvelle automatiquement chaque nuit dès qu&apos;il approche de son
        échéance — un jeton Instagram expire au bout de 60 jours, et sans ce renouvellement
        la publication s&apos;arrêterait sans prévenir. Enregistrer un jeton n&apos;active
        aucune publication : celle-ci reste commandée par un réglage distinct, côté serveur.
      </p>
    </div>
  );
}
