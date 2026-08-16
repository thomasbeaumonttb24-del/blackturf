"use client";

/**
 * Désabonnement des e-mails marketing (RGPD).
 *
 * Cible du lien « Se désabonner » présent dans les e-mails non transactionnels
 * (digest hebdomadaire « meilleur value bet de la semaine »). Le jeton signé est
 * passé en query string ; la page appelle l'API publique qui pose l'opt-out.
 *
 * Volontairement accessible SANS connexion : exiger un login pour exercer son
 * droit d'opposition reviendrait à ne pas offrir de désinscription réelle.
 *
 * Le POST n'est PAS déclenché au chargement mais sur clic explicite : les
 * antivirus/scanners de messagerie préchargent les liens des e-mails, ce qui
 * désabonnerait des utilisateurs qui n'ont jamais cliqué.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

function DesabonnementInner() {
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function confirmer() {
    setState("loading");
    try {
      const res = await api.post("/notifications/desabonnement", { token });
      setMessage(typeof res.data?.message === "string" ? res.data.message : null);
      setState("done");
    } catch (e: unknown) {
      // `detail` FastAPI n'est pas toujours une string (422 Pydantic = liste
      // d'objets) : ne jamais le rendre tel quel dans du texte.
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setMessage(typeof detail === "string" ? detail : null);
      setState("error");
    }
  }

  if (!token) {
    return (
      <Wrapper>
        <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-amber-500" />
        <h1 className="mb-2 text-xl font-bold">Lien incomplet</h1>
        <p className="text-sm text-muted-foreground">
          Ce lien de désabonnement ne contient pas de jeton. Utilisez le lien exact reçu dans l&apos;e-mail.
        </p>
      </Wrapper>
    );
  }

  if (state === "done") {
    return (
      <Wrapper>
        <CheckCircle2 className="mx-auto mb-3 h-10 w-10 text-emerald-500" />
        <h1 className="mb-2 text-xl font-bold">Désabonnement enregistré</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          {message || "Vous ne recevrez plus d'e-mails de ce type."}
        </p>
        <Button variant="outline" asChild>
          <Link href="/">Retour à l&apos;accueil</Link>
        </Button>
      </Wrapper>
    );
  }

  return (
    <Wrapper>
      <h1 className="mb-2 text-xl font-bold">Se désabonner des e-mails</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Confirmez pour ne plus recevoir les e-mails d&apos;actualité BlackTurf (paris de valeur de
        la semaine). Les e-mails liés à votre compte (sécurité, facturation) continueront d&apos;être envoyés.
      </p>
      {state === "error" && (
        <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {message || "Ce lien est invalide ou a expiré."}
        </p>
      )}
      <Button variant="brand" onClick={confirmer} disabled={state === "loading"}>
        {state === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Confirmer le désabonnement"}
      </Button>
    </Wrapper>
  );
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <div className="rounded-2xl border border-border p-8">{children}</div>
    </div>
  );
}

export default function DesabonnementPage() {
  // useSearchParams impose une frontière Suspense en App Router (sinon la page
  // bascule en rendu dynamique au build).
  return (
    <Suspense fallback={<Wrapper><Loader2 className="mx-auto h-6 w-6 animate-spin" /></Wrapper>}>
      <DesabonnementInner />
    </Suspense>
  );
}
