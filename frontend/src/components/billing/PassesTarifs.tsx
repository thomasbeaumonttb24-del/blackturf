"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Ticket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";

type Duree = "jour" | "semaine" | "mois";

// Prix affichés = prix encaissés (backend/services/passes.py, vérifiés au centime
// sur la session payée). Le serveur fixe le prix : le client n'envoie que la durée.
const PASSES: { duree: Duree; nom: string; prix: string; acces: string; note: string }[] = [
  { duree: "jour", nom: "Pass Jour", prix: "5 €", acces: "24 h d'accès Expert", note: "Idéal pour le Quinté du jour" },
  { duree: "semaine", nom: "Pass Semaine", prix: "12 €", acces: "7 jours d'accès Expert", note: "Une semaine de courses complète" },
  { duree: "mois", nom: "Pass Mois", prix: "24 €", acces: "30 jours d'accès Expert", note: "Sans abonnement, sans prélèvement suivant" },
];

// Texte identique à celui enregistré comme preuve côté serveur (RENONCIATION_TEXTE).
const RENONCIATION =
  "Je demande l'accès immédiat au service et je renonce expressément à mon droit de rétractation. " +
  "Paiement unique, sans renouvellement, non remboursable.";

function dateFin(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", {
    day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris",
  });
}

export function PassesTarifs() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [accepte, setAccepte] = useState(false);
  const [enCours, setEnCours] = useState<Duree | null>(null);
  // Abonné Expert : accès déjà illimité, le serveur refuserait (409).
  const expertAbonne = Boolean(user?.abonnement_gerable) && user?.plan === "expert" && !user?.pass_fin;

  async function acheter(duree: Duree) {
    if (!user) {
      router.push(`/inscription?suite=${encodeURIComponent("/tarifs#passes")}`);
      return;
    }
    if (!accepte) {
      toast.error("Cochez d'abord la case d'accès immédiat ci-dessous.");
      return;
    }
    setEnCours(duree);
    try {
      const r = await api.post("/stripe/pass", { duree, renonciation: true });
      window.location.assign(r.data.url);
    } catch (error: unknown) {
      const response = (error as { response?: { data?: { detail?: string }; status?: number } })?.response;
      toast.error(response?.data?.detail || "Impossible d'ouvrir le paiement sécurisé");
      if (response?.status === 403) router.push("/profil");
      setEnCours(null);
    }
  }

  return (
    <section id="passes" className="scroll-mt-24 mb-12 sm:mb-16">
      <div className="mb-6 text-center">
        <h2 className="text-2xl font-extrabold sm:text-3xl">Sans abonnement</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Tout BlackTurf en accès Expert, payé une fois. L&apos;accès s&apos;arrête seul : rien d&apos;autre ne sera prélevé.
        </p>
        {user?.pass_fin && (
          <p className="mx-auto mt-3 inline-block rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
            Votre pass est actif jusqu&apos;au {dateFin(user.pass_fin)} — un nouveau pass s&apos;ajoute à la suite.
          </p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {PASSES.map((p) => (
          <div key={p.duree} className="flex flex-col rounded-2xl border border-border bg-white p-5 sm:p-6">
            <div className="flex items-center gap-2">
              <Ticket className="h-4 w-4 text-brand-gold-dark" aria-hidden />
              <h3 className="font-bold">{p.nom}</h3>
            </div>
            <div className="mt-3 flex items-baseline gap-1">
              <span className="text-3xl font-extrabold">{p.prix}</span>
              <span className="text-xs text-muted-foreground">paiement unique</span>
            </div>
            <p className="mt-1 text-sm font-medium">{p.acces}</p>
            <p className="mb-5 mt-1 text-xs text-muted-foreground">{p.note}</p>
            <Button
              type="button"
              variant="outline"
              className="mt-auto w-full"
              disabled={authLoading || enCours !== null || expertAbonne || (Boolean(user) && !accepte)}
              onClick={() => acheter(p.duree)}
            >
              {enCours === p.duree ? <Loader2 className="h-4 w-4 animate-spin" /> : `Prendre le ${p.nom}`}
            </Button>
          </div>
        ))}
      </div>

      {expertAbonne ? (
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Votre abonnement Expert vous donne déjà un accès illimité.
        </p>
      ) : (
        <label className="mx-auto mt-5 flex max-w-2xl cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted/30 p-4 text-xs leading-snug">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 flex-shrink-0 accent-amber-500"
            checked={accepte}
            onChange={(e) => setAccepte(e.target.checked)}
          />
          <span>
            {RENONCIATION}{" "}
            <a href="/cgv#passes" className="underline">Conditions</a>
          </span>
        </label>
      )}
    </section>
  );
}
