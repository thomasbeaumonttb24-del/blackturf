"use client";

/**
 * Classement du Défi du mois EN DIRECT, en format compact : les premiers, leurs
 * points, et la place du joueur connecté même s'il est loin. Posé partout où on
 * veut donner envie de jouer (accueil, programme, courses, tableau de bord).
 */

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, CalendarDays, Crown, Medal } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { defiApi, type DefiClassement, type DefiLigne } from "@/lib/api";
import { formatPts, moisLabel, planLabel } from "@/components/defi/kit";
import { cn } from "@/lib/utils";

export function joursRestantsMois(mois: string): number {
  const [a, m] = mois.split("-").map(Number);
  if (!a || !m) return 0;
  // Fin du mois à minuit heure de Paris ≈ 22 h/23 h UTC la veille : l'arrondi au
  // jour supérieur suffit pour un compte à rebours affiché en jours.
  return Math.max(0, Math.ceil((Date.UTC(a, m, 1) - Date.now()) / 86_400_000));
}

function Ligne({ l }: { l: DefiLigne }) {
  return (
    <li className={cn("flex items-center gap-2.5 px-3 py-2", l.moi && "bg-amber-50")}>
      <span className={cn("inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums",
        l.rang === 1 ? "bg-amber-400 text-white" : l.rang === 2 ? "bg-slate-300 text-slate-800"
          : l.rang === 3 ? "bg-orange-300 text-orange-950" : "bg-stone-100 text-slate-600")}>
        {l.rang ?? "–"}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-slate-800">
        {l.nom}{l.moi && <span className="ml-1 text-[11px] text-amber-800">(vous)</span>}
      </span>
      <span className="text-[11px] tabular-nums text-slate-500">{l.nb_paris} paris</span>
      <span className="w-[76px] text-right font-display text-[13px] font-bold tabular-nums text-slate-900">{formatPts(l.solde)}</span>
    </li>
  );
}

export function DefiClassementLive({ top = 5, className, titre = "Défi du mois", ctaCourse }: {
  top?: number;
  className?: string;
  titre?: string;
  /** Sur une page course : le bouton ouvre l'onglet Défi au lieu de /defi. */
  ctaCourse?: () => void;
}) {
  const { user } = useAuth();
  const { data } = useSWR<DefiClassement>(
    ["/defi/classement/top", top, user?.user_id ?? ""],
    () => defiApi.classement(undefined, top).then((r) => r.data),
    { refreshInterval: 60_000 },
  );
  const { data: regles } = useSWR("/defi/regles", () => defiApi.regles().then((r) => r.data),
    { revalidateOnFocus: false });

  const prix = regles?.recompenses?.[0];
  const minParis = regles?.min_paris_classement ?? 10;
  const ma = data?.ma_ligne;
  const maVisible = ma && data?.lignes.some((l) => l.moi);
  const jours = data ? joursRestantsMois(data.mois) : null;

  return (
    <section aria-label="Classement du Défi du mois en direct"
      className={cn("overflow-hidden rounded-2xl bg-white ring-1 ring-inset ring-[#ECE7DC] shadow-[0_1px_2px_rgba(17,24,39,.05),0_12px_28px_-22px_rgba(17,24,39,.45)]", className)}>
      <header className="flex items-start justify-between gap-3 px-4 pb-3 pt-4">
        <div className="min-w-0">
          <h2 className="inline-flex items-center gap-2 font-display text-[15px] font-bold text-slate-900">
            <Medal className="h-4 w-4 text-amber-700" aria-hidden="true" /> {titre}
          </h2>
          <p className="mt-0.5 text-[11.5px] text-slate-600">
            {data ? moisLabel(data.mois) : "Classement"} · {data?.nb_joueurs ?? 0} joueur{(data?.nb_joueurs ?? 0) > 1 ? "s" : ""}
            {prix && <> · 1er = {prix.jours} j {planLabel(prix.plan)} offerts</>}
          </p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden="true" /> En direct
        </span>
      </header>

      {!data ? (
        <div className="space-y-2 px-4 pb-4" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-7 animate-pulse rounded-lg bg-stone-100" />)}
        </div>
      ) : data.lignes.length === 0 ? (
        <p className="mx-4 mb-3 rounded-xl bg-amber-50 px-3 py-3 text-[12.5px] leading-snug text-amber-900 ring-1 ring-inset ring-amber-200">
          <Crown className="mr-1 inline h-3.5 w-3.5 align-[-2px]" aria-hidden="true" />
          Personne n&apos;est encore classé ce mois-ci ({minParis} paris requis) : la 1re place est à prendre.
        </p>
      ) : (
        <ol className="divide-y divide-stone-100 border-y border-stone-100">
          {data.lignes.map((l) => <Ligne key={`${l.rang}-${l.nom}`} l={l} />)}
          {ma && !maVisible && (
            <>
              <li aria-hidden="true" className="px-3 py-0.5 text-center text-[11px] leading-none text-slate-400">⋯</li>
              <Ligne l={ma} />
            </>
          )}
        </ol>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <span className="inline-flex items-center gap-1.5 text-[11.5px] text-slate-600">
          <CalendarDays className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          {jours == null ? "" : jours <= 1 ? "Dernier jour !" : `Fin dans ${jours} jours`}
          {ma && ma.rang == null && <> · encore {Math.max(0, minParis - ma.nb_paris)} paris pour être classé</>}
        </span>
        {ctaCourse ? (
          <button type="button" onClick={ctaCourse}
            className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-amber-800 px-3 text-[12px] font-bold text-white">
            Parier sur cette course <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : (
          <Link href="/defi" className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-amber-800 px-3 text-[12px] font-bold text-white">
            {user ? "Voir le classement" : "Participer gratuitement"} <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        )}
      </div>
    </section>
  );
}
