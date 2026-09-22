import Link from "next/link";
import { Check, Lock, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Appel à créer un compte GRATUIT — pour le visiteur anonyme, là où il bute sur
 * ce qu'un compte ouvre (marché des cotes en direct, calculateur de mise…).
 *
 * Distinct du bandeau d'abonnement (`CtaAbonnementBand`) : ici on ne vend rien,
 * on montre ce que 30 secondes d'inscription débloquent. Avant, le marché des
 * cotes disparaissait sans un mot pour l'anonyme (401 → `return null`), et le
 * calculateur n'offrait qu'un « Se connecter » à quelqu'un qui n'a pas de compte.
 *
 * `suite` : la page où revenir après confirmation de l'adresse (cf. intentionEssai).
 */
export const AVANTAGES_COMPTE_GRATUIT = [
  "Marché des cotes en direct sur chaque course",
  "Classement IA complet sur 1 course par jour",
  "1 plan de mise calculé sur votre budget par jour",
  "7 jours d'essai Standard offerts",
];

export function CompteGratuitCta({
  titre,
  texte,
  suite,
  icone: Icone = Lock,
  avantages = AVANTAGES_COMPTE_GRATUIT,
  className,
}: {
  titre: string;
  texte: string;
  suite: string;
  icone?: LucideIcon;
  avantages?: string[];
  className?: string;
}) {
  const q = encodeURIComponent(suite);
  return (
    <section
      className={cn(
        "rounded-[20px] border border-amber-200 bg-gradient-to-br from-amber-50 via-white to-emerald-50/40 p-5 sm:p-6",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800 ring-1 ring-amber-200">
          <Icone className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 className="font-display text-[16px] font-bold leading-snug text-slate-900">{titre}</h3>
          <p className="mt-1 text-[13px] leading-6 text-stone-600">{texte}</p>
        </div>
      </div>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {avantages.map((a) => (
          <li key={a} className="flex items-center gap-2 text-[13px] text-slate-700">
            <Check className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
            {a}
          </li>
        ))}
      </ul>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Link
          href={`/inscription?suite=${q}`}
          className="inline-flex items-center rounded-xl bg-brand-gold px-5 py-2.5 text-sm font-bold text-brand-dark shadow-sm shadow-brand-gold/25 ring-1 ring-brand-gold/30 transition-transform hover:-translate-y-0.5"
        >
          Créer mon compte gratuit
        </Link>
        <Link
          href={`/login?redirect=${q}`}
          className="text-sm font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900"
        >
          J&apos;ai déjà un compte
        </Link>
        <span className="text-xs text-stone-500">Compte gratuit : aucune carte demandée à l&apos;inscription.</span>
      </div>
    </section>
  );
}
