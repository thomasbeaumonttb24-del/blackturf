"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CalendarDays, CalendarRange, Check, CreditCard, Loader2, ShieldCheck, Sun, Timer, Zap } from "lucide-react";
import { toast } from "sonner";
import { Tilt } from "@/components/track-record/effets";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Duree = "jour" | "semaine" | "mois";

// Prix affichés = prix encaissés (backend/services/passes_catalogue.py, vérifiés au
// centime sur la session payée). Le serveur fixe le prix : le client n'envoie que la durée.
const PASSES: {
  duree: Duree; nom: string; prix: string; parJour: string; acces: string; pour: string;
  icone: typeof Sun; vedette?: string;
}[] = [
  { duree: "jour", nom: "Pass Jour", prix: "5", parJour: "5 € la journée", acces: "24 h d'accès Expert",
    pour: "Le Quinté du jour, une grosse réunion", icone: Sun },
  { duree: "semaine", nom: "Pass Semaine", prix: "12", parJour: "1,71 € par jour", acces: "7 jours d'accès Expert",
    pour: "Une semaine de courses complète", icone: CalendarDays },
  { duree: "mois", nom: "Pass Mois", prix: "24", parJour: "0,80 € par jour", acces: "30 jours d'accès Expert",
    pour: "Un mois entier, sans prélèvement suivant", icone: CalendarRange, vedette: "Meilleur prix par jour" },
];

// Ce que débloque un pass = la formule Expert (contrôles d'accès réels du backend).
const INCLUS = [
  "Classement de l'algorithme illimité",
  "Paris de valeur en temps réel",
  "Plan de mise illimité",
  "Assistant IA et créateur de stratégies",
];

// Texte identique à celui enregistré comme preuve côté serveur (RENONCIATION_TEXTE).
const RENONCIATION =
  "Je demande l'accès immédiat au service et je renonce expressément à mon droit de rétractation. " +
  "Paiement unique, sans renouvellement, non remboursable.";

const ETAPES = [
  { icone: ShieldCheck, titre: "Vous choisissez", texte: "Cochez la case d'accès immédiat puis votre durée." },
  { icone: CreditCard, titre: "Vous payez une fois", texte: "Paiement sécurisé par Stripe. Aucun abonnement créé." },
  { icone: Zap, titre: "Tout est ouvert", texte: "Accès Expert immédiat, coupé seul à la fin. Rien à résilier." },
];

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
      document.getElementById("renonciation-pass")?.focus();
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
    <section id="passes" aria-labelledby="titre-passes" className="scroll-mt-24 mb-12 sm:mb-16">
      {/* En-tête */}
      <div className="mb-8 text-center">
        <p className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-800 ring-1 ring-emerald-200">
          <Timer className="h-3.5 w-3.5" aria-hidden /> Sans abonnement
        </p>
        <h2 id="titre-passes" className="mt-3 font-display text-2xl font-extrabold tracking-tight sm:text-4xl">
          Tout BlackTurf, <span className="text-gradient">le temps qu&apos;il vous faut</span>
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground sm:text-base">
          Un pass, c&apos;est l&apos;accès Expert complet, payé une seule fois. À la fin de la durée choisie,
          l&apos;accès s&apos;arrête tout seul : aucun prélèvement ne suit.
        </p>
        {user?.pass_fin && (
          <p className="mx-auto mt-4 inline-flex items-center gap-2 rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white shadow-[0_8px_20px_-8px_rgba(5,150,105,.8)]">
            <Check className="h-3.5 w-3.5" aria-hidden />
            Pass actif jusqu&apos;au {dateFin(user.pass_fin)} — un nouveau pass s&apos;ajoute à la suite
          </p>
        )}
      </div>

      {/* Cartes */}
      <div className="grid gap-5 md:grid-cols-3 md:items-stretch" style={{ perspective: "1200px" }}>
        {PASSES.map((p) => {
          const vedette = Boolean(p.vedette);
          const Icone = p.icone;
          const bloque = authLoading || enCours !== null || expertAbonne;
          return (
            <Tilt key={p.duree} max={6} className="h-full">
              <div
                className={cn(
                  "relative flex h-full flex-col rounded-3xl p-6 transition-shadow sm:p-7",
                  vedette
                    ? "bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 text-white ring-2 ring-amber-400/70 shadow-[0_30px_60px_-25px_rgba(6,78,59,.7)]"
                    : "bg-white ring-1 ring-stone-200 shadow-[0_24px_50px_-30px_rgba(17,24,39,.45)] hover:shadow-[0_30px_60px_-28px_rgba(17,24,39,.55)]",
                )}
              >
                {vedette && (
                  <span className="absolute -top-3.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-gradient-to-b from-amber-300 to-amber-500 px-3 py-1 text-xs font-bold text-stone-900 shadow">
                    {p.vedette}
                  </span>
                )}

                <div className="flex items-center gap-3">
                  {/* Pastille en relief : dégradé + liseré clair + ombre portée. */}
                  <span
                    className={cn(
                      "flex h-11 w-11 items-center justify-center rounded-2xl shadow-[inset_0_1px_0_rgba(255,255,255,.6),0_10px_20px_-10px_rgba(0,0,0,.5)]",
                      vedette ? "bg-gradient-to-b from-amber-300 to-amber-500 text-stone-900" : "bg-gradient-to-b from-emerald-400 to-emerald-600 text-white",
                    )}
                    aria-hidden
                  >
                    <Icone className="h-5 w-5" />
                  </span>
                  <div>
                    <h3 className="text-lg font-bold leading-tight">{p.nom}</h3>
                    <p className={cn("text-xs", vedette ? "text-stone-300" : "text-muted-foreground")}>{p.acces}</p>
                  </div>
                </div>

                <div className="mt-5 flex items-baseline gap-1.5">
                  <span className={cn("font-display text-5xl font-extrabold tracking-tight", vedette && "text-amber-300")}>{p.prix}&nbsp;€</span>
                  <span className={cn("text-xs", vedette ? "text-stone-300" : "text-muted-foreground")}>une seule fois</span>
                </div>
                <p className={cn("mt-1 text-xs font-semibold", vedette ? "text-emerald-300" : "text-emerald-700")}>{p.parJour}</p>
                <p className={cn("mt-3 text-sm", vedette ? "text-stone-200" : "text-stone-700")}>{p.pour}</p>

                <ul className="mb-6 mt-4 space-y-2">
                  {INCLUS.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm">
                      <Check className={cn("mt-0.5 h-4 w-4 flex-shrink-0", vedette ? "text-emerald-300" : "text-emerald-600")} aria-hidden />
                      <span className={vedette ? "text-stone-200" : "text-stone-700"}>{f}</span>
                    </li>
                  ))}
                </ul>

                <button
                  type="button"
                  disabled={bloque}
                  aria-disabled={bloque || (Boolean(user) && !accepte)}
                  onClick={() => acheter(p.duree)}
                  className={cn(
                    "mt-auto inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0",
                    vedette
                      ? "bg-gradient-to-b from-amber-300 to-amber-500 text-stone-900 shadow-[0_10px_24px_-10px_rgba(245,158,11,.9),inset_0_1px_0_rgba(255,255,255,.5)]"
                      : "bg-stone-900 text-white shadow-[0_10px_24px_-12px_rgba(17,24,39,.9),inset_0_1px_0_rgba(255,255,255,.15)] hover:bg-stone-800",
                    Boolean(user) && !accepte && "opacity-60",
                  )}
                >
                  {enCours === p.duree ? <Loader2 className="h-4 w-4 animate-spin" /> : `Prendre le ${p.nom}`}
                </button>
              </div>
            </Tilt>
          );
        })}
      </div>

      {/* Renonciation : obligatoire avant tout paiement (vérifiée aussi côté serveur). */}
      {expertAbonne ? (
        <p className="mt-5 text-center text-sm text-muted-foreground">
          Votre abonnement Expert vous donne déjà un accès illimité : un pass ne vous apporterait rien.
        </p>
      ) : (
        <label
          htmlFor="renonciation-pass"
          className={cn(
            "mx-auto mt-6 flex max-w-2xl cursor-pointer items-start gap-3 rounded-2xl border p-4 text-xs leading-snug transition-colors",
            accepte ? "border-emerald-300 bg-emerald-50/70" : "border-amber-300 bg-amber-50/70",
          )}
        >
          <input
            id="renonciation-pass"
            type="checkbox"
            className="mt-0.5 h-4 w-4 flex-shrink-0 accent-emerald-600"
            checked={accepte}
            onChange={(e) => setAccepte(e.target.checked)}
          />
          <span>
            <b className="font-semibold">À cocher avant de payer.</b> {RENONCIATION}{" "}
            <Link href="/cgv#passes" className="underline">Conditions</Link>
          </span>
        </label>
      )}

      {/* Comment ça marche */}
      <ol className="mt-8 grid gap-3 sm:grid-cols-3">
        {ETAPES.map((e, i) => (
          <li key={e.titre} className="flex items-start gap-3 rounded-2xl bg-white p-4 ring-1 ring-stone-200 shadow-[0_14px_30px_-24px_rgba(17,24,39,.5)]">
            <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-stone-900 text-sm font-bold text-amber-300 shadow-[inset_0_1px_0_rgba(255,255,255,.15)]">
              {i + 1}
            </span>
            <div>
              <p className="flex items-center gap-1.5 text-sm font-semibold">
                <e.icone className="h-4 w-4 text-emerald-600" aria-hidden /> {e.titre}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">{e.texte}</p>
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-5 text-center text-xs text-muted-foreground">
        Vous jouez toutes les semaines ? L&apos;abonnement{" "}
        <Link href="#formules" className="font-semibold text-foreground underline">Expert à 19 €/mois</Link>{" "}
        revient moins cher qu&apos;un Pass Mois, et reste résiliable à tout moment.
      </p>
    </section>
  );
}
