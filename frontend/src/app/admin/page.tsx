"use client";

/**
 * Pilotage — l'écran d'accueil de la console.
 *
 * Refonte du 2026-09-14 : quatre chiffres (argent, payants, essais, comptes),
 * qui est sur le site maintenant, ce qui demande une action, ce que rapportent
 * les plans. Le reste (tuiles modèle, raccourcis, paragraphes d'explication) est
 * parti : la navigation latérale mène déjà partout, et le modèle figé remonte
 * dans « À traiter ».
 */

import { useState } from "react";
import { toast } from "sonner";
import { CreditCard, Gauge, Hourglass, Loader2, RefreshCw, Users, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { adminApi } from "@/lib/api";
import { EnTetePage, GrilleKpi, Kpi, depuis, eur, num } from "@/components/admin/ui";
import { useAbonnements, useDashboard } from "@/components/admin/data";
import BandeauAlertes from "@/components/admin/vues/BandeauAlertes";
import EnDirect from "@/components/admin/vues/EnDirect";
import RentabiliteProfils from "@/components/admin/vues/RentabiliteProfils";

export default function PilotagePage() {
  const { data: dashboard } = useDashboard();
  const { data: abos } = useAbonnements();
  const [retraining, setRetraining] = useState(false);
  const r = abos?.repartition;

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
    <div className="space-y-5 sm:space-y-6">
      <EnTetePage
        titre="Pilotage"
        icone={<Gauge className="h-4 w-4" />}
        desc={dashboard?.modele.version
          ? `Modèle v${dashboard.modele.version} · entraîné ${depuis(dashboard.modele.trained_at)}`
          : undefined}
        actions={
          <Button variant="brand" onClick={lancerRetrain} disabled={retraining} className="min-h-[2.75rem]">
            {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Ré-entraîner
          </Button>
        }
      />

      <GrilleKpi>
        <Kpi
          label="Revenu mensuel"
          valeur={abos ? eur(abos.resume.mrr) : "—"}
          sub={abos ? `${eur(abos.resume.arr)} par an` : undefined}
          icone={<Wallet className="h-4 w-4" />}
          accent="or"
        />
        <Kpi
          label="Payants"
          valeur={num(r?.payants)}
          sub={r ? `Standard ${r.par_formule.standard.payants} · Expert ${r.par_formule.expert.payants}` : undefined}
          icone={<CreditCard className="h-4 w-4" />}
          accent="ok"
        />
        <Kpi
          label="En essai"
          valeur={num(r?.essais)}
          sub={abos
            ? abos.resume.fin_essai_sous_3j > 0
              ? `${abos.resume.fin_essai_sous_3j} finissent sous 3 j`
              : "aucun ne finit sous 3 j"
            : undefined}
          icone={<Hourglass className="h-4 w-4" />}
          accent="bleu"
        />
        <Kpi
          label="Comptes"
          valeur={num(r?.comptes)}
          sub={dashboard ? `+${dashboard.users.nouveaux_7j} cette semaine` : undefined}
          icone={<Users className="h-4 w-4" />}
        />
      </GrilleKpi>

      {/* Côte à côte seulement dès 1280 px : entre 1024 et 1280, la barre latérale
          laisse ~700 px et le bloc « en direct » tronquait chaque adresse. */}
      <div className="grid gap-5 xl:grid-cols-5 xl:items-start xl:gap-6">
        <EnDirect className="xl:col-span-2" />
        <div className="xl:col-span-3">
          <BandeauAlertes />
        </div>
      </div>

      <RentabiliteProfils />
    </div>
  );
}
