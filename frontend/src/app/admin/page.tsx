"use client";

/**
 * Pilotage — l'écran d'accueil de la console.
 *
 * L'ancienne page `/admin` faisait 1 515 lignes et empilait TOUT : comptage
 * d'utilisateurs, erreurs runtime, rentabilité, abonnements, journal Stripe,
 * modèle actif, historique des modèles, scrapers, gestion des comptes. Sur
 * téléphone, ça faisait une quinzaine d'écrans de défilement sans un seul
 * repère — et l'information la plus urgente (un paiement échoué) se trouvait
 * au milieu, dans une section repliée.
 *
 * Elle est découpée en quatre écrans (Pilotage, Abonnements, Comptes, Système)
 * reliés par une navigation permanente. Celui-ci ne répond qu'à une question :
 * est-ce que quelque chose demande mon attention, et combien ça rapporte.
 */

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  Activity, ArrowRight, Brain, CreditCard, Gauge, Loader2, RefreshCw, Users, Wallet,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { adminApi } from "@/lib/api";
import { formatDateTime, formatEuro } from "@/lib/utils";
import { EnTetePage, GrilleTuiles, Panneau, Puce, Tuile, depuis, num, pct } from "@/components/admin/ui";
import { useAbonnements, useDashboard, useModeles } from "@/components/admin/data";
import BandeauAlertes from "@/components/admin/vues/BandeauAlertes";
import RentabiliteProfils from "@/components/admin/vues/RentabiliteProfils";

const RACCOURCIS = [
  {
    href: "/admin/abonnements",
    titre: "Abonnements",
    desc: "Essais en cours, cartes manquantes, journal Stripe",
    icone: CreditCard,
  },
  {
    href: "/admin/comptes",
    titre: "Comptes",
    desc: "Portefeuilles, suspensions, export CSV",
    icone: Users,
  },
  {
    href: "/admin/algorithme",
    titre: "Supervision IA",
    desc: "Ce que l'algorithme a conseillé et ce que ça a rapporté",
    icone: Brain,
  },
] as const;

export default function PilotagePage() {
  const { data: dashboard } = useDashboard();
  const { data: abos } = useAbonnements();
  const { data: modeles } = useModeles();
  const [retraining, setRetraining] = useState(false);

  const actif = modeles?.find((m) => m.est_actif);

  async function lancerRetrain() {
    setRetraining(true);
    try {
      await adminApi.retrain();
      toast.success("Ré-entraînement lancé en arrière-plan");
    } catch {
      toast.error("Le déclenchement a échoué");
    } finally {
      setRetraining(false);
    }
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <EnTetePage
        titre="Pilotage"
        icone={<Gauge className="h-4 w-4" />}
        desc="État de la plateforme en direct. Les chiffres se rafraîchissent seuls ; une valeur absente s'affiche « — », jamais zéro."
        actions={
          <Button variant="brand" onClick={lancerRetrain} disabled={retraining} className="min-h-[2.75rem]">
            {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Ré-entraîner
          </Button>
        }
      />

      <BandeauAlertes />

      <Panneau
        titre="Activité"
        desc="Le socle : combien de personnes, combien de courses traitées, quel modèle sert les pronostics."
        icone={<Activity className="h-3.5 w-3.5" />}
      >
        <GrilleTuiles colonnes={5}>
          <Tuile
            label="Utilisateurs"
            valeur={num(dashboard?.users.total)}
            sub={dashboard ? `+${dashboard.users.nouveaux_7j} cette semaine` : undefined}
            icone={<Users className="h-3.5 w-3.5" />}
          />
          <Tuile
            label="Abonnés actifs"
            valeur={num(dashboard?.users.abonnes_actifs)}
            sub={abos ? `${abos.resume.abonnes_payants} payant(s) · ${abos.resume.en_essai_avec_carte} en essai` : undefined}
            icone={<CreditCard className="h-3.5 w-3.5" />}
          />
          <Tuile
            label="Revenu mensuel"
            valeur={abos ? formatEuro(abos.resume.mrr) : "—"}
            sub={abos ? `ARR ${formatEuro(abos.resume.arr)}` : undefined}
            icone={<Wallet className="h-3.5 w-3.5" />}
            aide="MRR : somme des abonnements actifs ramenée au mois. Les essais n'y comptent pas tant qu'ils n'ont pas été facturés."
          />
          <Tuile
            label="Courses 24 h"
            valeur={num(dashboard?.courses_24h)}
            sub="analysées et réglées"
            icone={<Activity className="h-3.5 w-3.5" />}
          />
          <Tuile
            label="Modèle actif"
            valeur={dashboard?.modele.version ? `v${dashboard.modele.version}` : "—"}
            sub={dashboard?.modele.trained_at ? `entraîné ${depuis(dashboard.modele.trained_at)}` : "aucun modèle déployé"}
            icone={<Brain className="h-3.5 w-3.5" />}
            ton={dashboard && !dashboard.modele.version ? "alerte" : "neutre"}
          />
        </GrilleTuiles>

        {dashboard?.modele.version && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Puce ton="ok">AUC {dashboard.modele.auc_roc?.toFixed(4) ?? "—"}</Puce>
            <Puce>Top-3 {pct((dashboard.modele.precision_top3 ?? 0) * 100)}</Puce>
            {actif && <Puce>{num(actif.nb_courses_train)} partants d&apos;entraînement</Puce>}
            {dashboard.modele.trained_at && (
              <span className="text-xs text-muted-foreground">
                le {formatDateTime(dashboard.modele.trained_at)}
              </span>
            )}
          </div>
        )}
      </Panneau>

      <RentabiliteProfils />

      <Panneau titre="Aller plus loin" desc="Le reste de la console, par sujet.">
        <div className="grid gap-2.5 sm:grid-cols-3">
          {RACCOURCIS.map((r) => {
            const Icone = r.icone;
            return (
              <Link
                key={r.href}
                href={r.href}
                className="group flex min-h-[4.5rem] items-start gap-3 rounded-xl border border-border p-3 transition-colors hover:border-brand-gold/40 hover:bg-brand-gold-light/40"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground transition-colors group-hover:bg-brand-gold/10 group-hover:text-brand-gold-dark">
                  <Icone className="h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1 text-[13px] font-semibold">
                    {r.titre}
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    {r.desc}
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      </Panneau>
    </div>
  );
}
