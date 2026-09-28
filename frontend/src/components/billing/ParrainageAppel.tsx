"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Copy, Gift } from "lucide-react";
import { toast } from "sonner";
import { parrainageApi, type ResumeParrainage } from "@/lib/api";
import { euros } from "@/lib/parrainage";
import { cn } from "@/lib/utils";
import { Tilt } from "@/components/track-record/effets";
import { Anneau } from "@/components/espace/kit";

/**
 * Incitation au parrainage, là où l'utilisateur passe : « Mon espace » et
 * l'écran de bienvenue après abonnement.
 *
 * Le lien se copie ICI, sans détour par le profil : chaque clic en moins
 * compte. Si le résumé n'est pas lisible (adresse non confirmée, API
 * injoignable), la carte reste utile et renvoie vers l'onglet Parrainage.
 */
export function ParrainageAppel({ contexte = "espace", className }: {
  contexte?: "espace" | "bienvenue";
  className?: string;
}) {
  const [data, setData] = useState<ResumeParrainage | null>(null);
  const [copie, setCopie] = useState(false);

  useEffect(() => {
    parrainageApi.moi().then(({ data }) => setData(data)).catch(() => {});
  }, []);

  async function copier() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.lien);
      setCopie(true);
      toast.success("Lien copié : envoyez-le à vos amis");
      setTimeout(() => setCopie(false), 2000);
    } catch {
      toast.error("Copie impossible : ouvrez l'onglet Parrainage de votre profil.");
    }
  }

  const mois = data?.mois;
  const facture = data?.deduction.situation === "facture" ? data.deduction : null;
  const plafond = mois?.plafond ?? 4;
  const poses = mois?.poses ?? 0;
  const reste = Math.max(0, plafond - poses);
  const formule = mois?.formule === "standard" ? "Standard" : "Expert";

  const titre = contexte === "bienvenue"
    ? "Votre prochain mois peut être gratuit"
    : poses > 0 && reste > 0
      ? `Encore ${reste} ami${reste > 1 ? "s" : ""} et votre prochain mois est offert`
      : poses >= plafond && mois
        ? "Votre prochaine mensualité est couverte"
        : "Invitez vos amis, ne payez plus votre abonnement";

  return (
    <Tilt max={4} className={cn("rounded-3xl", className)}>
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-stone-800 p-5 text-left text-white shadow-[0_30px_60px_-30px_rgba(28,25,23,.7)] ring-1 ring-white/10 sm:p-7">
        <span className="tr-shine" aria-hidden />
        <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-amber-400/20 blur-3xl" aria-hidden />
        <div className="absolute -bottom-20 -left-16 h-56 w-56 rounded-full bg-emerald-400/15 blur-3xl" aria-hidden />

        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:gap-7">
          <div className="tr-pop flex shrink-0 items-center gap-4 sm:flex-col sm:gap-2">
            {mois ? (
              <Anneau pct={(poses / plafond) * 100} taille={88} epaisseur={8} couleur={["#FCD34D", "#10B981"]}>
                <span className="font-display text-2xl font-semibold leading-none">{poses}<span className="text-sm text-stone-400">/{plafond}</span></span>
                <span className="mt-0.5 text-[9px] uppercase tracking-[0.15em] text-stone-400">ce mois</span>
              </Anneau>
            ) : (
              <span className="tr-medal flex h-[88px] w-[88px] items-center justify-center rounded-3xl bg-gradient-to-br from-amber-200 to-amber-500 text-stone-900 shadow-[0_18px_30px_-12px_rgba(0,0,0,.6),inset_0_1px_0_rgba(255,255,255,.6)]">
                <Gift className="h-10 w-10" aria-hidden />
              </span>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">
              <Gift className="h-3.5 w-3.5" aria-hidden /> Parrainage
            </p>
            <h3 className="mt-2 font-display text-xl font-semibold leading-tight tracking-tight sm:text-2xl">{titre}</h3>
            <p className="mt-2 text-sm leading-relaxed text-stone-300">
              Chaque ami qui s&apos;abonne avec votre lien : <span className="font-semibold text-white">5 € pour lui, 5 € de moins sur votre mensualité</span>.
              {" "}{formule === "Expert" ? "4 amis = votre mois Expert offert." : "3 amis = votre mois Standard offert."}
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              {data ? (
                <button
                  onClick={copier}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-2.5 text-sm font-semibold text-stone-900 shadow-[0_8px_20px_-8px_rgba(245,158,11,.8),inset_0_1px_0_rgba(255,255,255,.5)] transition-transform hover:-translate-y-0.5"
                >
                  {copie ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copie ? "Lien copié" : "Copier mon lien"}
                </button>
              ) : null}
              <Link
                href="/profil#parrainage"
                className="inline-flex items-center gap-1.5 rounded-xl bg-white/10 px-4 py-2.5 text-sm font-semibold text-white ring-1 ring-white/20 transition-all hover:-translate-y-0.5 hover:bg-white/15"
              >
                {data ? "Mon suivi" : "Obtenir mon lien"} <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            </div>
            {data && data.valides > 0 && (
              <p className="mt-3 text-xs text-stone-400">
                Déjà {data.valides} ami{data.valides > 1 ? "s" : ""} abonné{data.valides > 1 ? "s" : ""} grâce à vous · {euros(data.gagne_cents)} gagnés
              </p>
            )}
          </div>

          {/* Grand écran, « Mon espace » : la prochaine facture réelle, crédit déduit. */}
          {contexte === "espace" && facture && (
            <div className="tr-pop hidden shrink-0 lg:block">
              <div className="relative w-52 rotate-[2deg] rounded-2xl bg-gradient-to-br from-stone-50 to-white p-4 text-stone-900 shadow-[0_24px_40px_-16px_rgba(0,0,0,.7),inset_0_1px_0_rgba(255,255,255,.8)]">
                <span className="absolute -left-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-stone-900" aria-hidden />
                <span className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-stone-900" aria-hidden />
                <p className="whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.15em] text-stone-500">Prochaine facture</p>
                {facture.date && (
                  <p className="text-xs text-stone-500">le {new Date(facture.date).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}</p>
                )}
                <div className="mt-2 flex items-baseline justify-between gap-2">
                  {facture.total_cents !== facture.a_payer_cents && (
                    <span className="text-sm text-stone-400 line-through tabular-nums">{euros(facture.total_cents)}</span>
                  )}
                  <span className="ml-auto font-display text-3xl font-semibold tabular-nums">{euros(facture.a_payer_cents)}</span>
                </div>
                <div className="mt-3 border-t border-dashed border-stone-200 pt-2 text-[11px] font-semibold text-emerald-700">
                  {facture.total_cents !== facture.a_payer_cents
                    ? `−${euros(facture.total_cents - facture.a_payer_cents)} grâce à vos amis`
                    : "Invitez un ami : −5 € ici"}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </Tilt>
  );
}
