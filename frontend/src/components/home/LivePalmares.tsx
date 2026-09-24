"use client";

/**
 * Palmarès en direct de la page d'accueil.
 *
 * Même langage visuel que /track-record : podium 3D des trois plus gros gains sur
 * scène sombre, puis les derniers paris gagnés en tickets (jour ET heure de départ
 * de la course, jetons de chevaux, gain net). Les composants sont partagés
 * (`BetsShowcase`) : un pari se lit de la même façon sur les deux pages.
 *
 * Endpoint PUBLIC : `palmaresGagnants` est gardé par require_admin (401 visiteur) —
 * cette section, principale preuve sociale du site, n'était visible que par l'admin.
 */

import useSWR from "swr";
import Link from "next/link";
import { Trophy, Clock, ShieldCheck, ArrowRight, Lock, Star, Receipt, Target } from "lucide-react";
import { statsApi } from "@/lib/api";
import { Reveal, Tilt } from "@/components/track-record/effets";
import { Podium, TicketsGrid, eur, type WinningBet } from "@/components/track-record/BetsShowcase";

interface PalmaresResp {
  gagnants: WinningBet[];
  top_gains: WinningBet[];
  nb_paris_gagnes?: number;
  nb_courses_gagnantes?: number;
  nb_courses_reglees?: number;
  updated_at?: string;
}

const fetcher = () => statsApi.palmaresPublic().then((r) => r.data as PalmaresResp);
const fmtInt = (n: number) => n.toLocaleString("fr-FR");

export function LivePalmares() {
  const { data } = useSWR<PalmaresResp>("palmares-public", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  const top = data?.top_gains ?? [];
  const recent = (data?.gagnants ?? []).slice(0, 6);
  const hasData = top.length > 0 || recent.length > 0;

  const nbGagnes = data?.nb_paris_gagnes ?? null;
  const nbCourses = data?.nb_courses_reglees ?? null;
  const meilleurGain = top.length > 0 ? top[0].benefice : null;

  return (
    <section className="bg-[#FCFBF8] py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <Reveal className="mb-10 text-center">
          <span className="inline-flex items-center gap-2 rounded-full bg-amber-100/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-amber-900 ring-1 ring-amber-200">
            <Trophy className="h-3.5 w-3.5" aria-hidden="true" /> Palmarès en direct
          </span>
          <h2 className="mt-3 font-display text-[1.65rem] font-extrabold leading-tight tracking-tight text-gray-900 sm:text-4xl">
            Les paris gagnants du site,{" "}
            <span className="text-gradient">en temps réel</span>
          </h2>
          <p className="mx-auto mt-3 max-w-2xl text-[15px] leading-7 text-gray-600">
            <span className="inline-flex items-center gap-1.5">
              <span className="live-dot inline-block h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
              Mis à jour à chaque fin de course
            </span>{" "}
            · pronostics figés <strong className="text-gray-800">avant le départ</strong>, réglés aux vrais rapports PMU.
          </p>
        </Reveal>

        {/* ── Chiffres : les gagnants AVEC leur dénominateur ──
            Afficher les paris gagnants sans dire sur combien de courses ils ont été
            joués serait un biais du survivant. Les deux nombres vont ensemble. */}
        {hasData && nbGagnes != null && nbCourses != null && (
          <div className="mb-10 grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
            {[
              { icon: Receipt, v: fmtInt(nbGagnes), l: "paris gagnants enregistrés", cls: "text-gray-900", tile: "from-slate-700 to-slate-950 text-amber-300" },
              { icon: Target, v: fmtInt(nbCourses), l: "courses réglées, gagnées et perdues", cls: "text-gray-900", tile: "from-amber-300 to-amber-600 text-slate-950" },
              { icon: Star, v: meilleurGain != null ? `+${eur(meilleurGain, 0)}` : "—", l: "meilleur gain net sur un pari", cls: "text-emerald-700", tile: "from-emerald-400 to-emerald-700 text-white" },
            ].map((k, i) => (
              <Reveal key={k.l} delay={i * 90}>
                <Tilt max={8} className="flex h-full items-center gap-4 rounded-2xl bg-white p-4 ring-1 ring-stone-200/80 shadow-[0_22px_44px_-32px_rgba(17,24,39,.5)] sm:p-5">
                  <span className={`tr-pop inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-[inset_0_1px_0_rgba(255,255,255,.35),0_10px_18px_-10px_rgba(0,0,0,.5)] ${k.tile}`}>
                    <k.icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <div className={`font-display text-2xl font-black tabular-nums ${k.cls}`}>{k.v}</div>
                    <div className="text-xs leading-tight text-gray-600">{k.l}</div>
                  </div>
                </Tilt>
              </Reveal>
            ))}
          </div>
        )}

        {!hasData ? (
          <div className="rounded-3xl border border-dashed border-gray-200 bg-white px-6 py-12 text-center">
            <Clock className="mx-auto mb-3 h-8 w-8 text-gray-300" />
            <p className="text-sm font-semibold text-gray-700">Les premiers paris gagnants s&apos;afficheront ici</p>
            <p className="mt-1 text-xs text-gray-600">Dès la fin des prochaines courses, chaque pari gagné apparaît automatiquement.</p>
          </div>
        ) : (
          <>
            {top.length > 0 && (
              <div className="relative isolate -mx-4 overflow-hidden bg-[#0b1020] px-4 py-10 sm:mx-0 sm:rounded-[2rem] sm:px-8 sm:py-12 lg:px-10">
                <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
                  <span className="tr-glow absolute -left-24 top-6 h-72 w-72 rounded-full bg-amber-500/20 blur-[100px]" />
                  <span className="tr-glow absolute -right-24 top-1/3 h-80 w-80 rounded-full bg-indigo-500/15 blur-[110px]" style={{ animationDelay: "2s" }} />
                  <span className="tr-floor" />
                </div>
                <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between lg:mb-12">
                  <div>
                    <p className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-amber-300">
                      <Star className="h-3.5 w-3.5" aria-hidden="true" /> Records
                    </p>
                    <h3 className="mt-1 font-display text-2xl font-extrabold text-white sm:text-3xl">Les 3 plus gros gains</h3>
                  </div>
                  <Link href="/track-record#records" className="inline-flex items-center gap-1 text-sm font-semibold text-amber-300 hover:text-amber-200">
                    Voir les 30 records <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </div>
                <Podium bets={top} />
              </div>
            )}

            {recent.length > 0 && (
              <div className="mt-12">
                <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <h3 className="flex items-center gap-2 font-display text-xl font-bold text-gray-900 sm:text-2xl">
                    <span className="live-dot inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden="true" />
                    Les derniers paris gagnés
                  </h3>
                  <Link href="/track-record" className="inline-flex items-center gap-1 text-sm font-semibold text-amber-800 hover:text-amber-900">
                    Voir les 50 derniers <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </div>
                <TicketsGrid bets={recent} />
              </div>
            )}
          </>
        )}

        {/* ── CTA abonnement — sans promesse de gain (contrainte ANJ) ── */}
        {hasData && (
          <Reveal delay={120}>
            <div className="mt-10 flex flex-col items-center justify-between gap-4 rounded-3xl bg-gradient-to-r from-amber-50 via-white to-white px-5 py-6 ring-1 ring-amber-200 shadow-[0_24px_50px_-40px_rgba(180,83,9,.6)] sm:flex-row sm:px-8">
              <div className="text-center sm:text-left">
                <p className="text-[15px] font-semibold text-gray-900">
                  Ces paris sont publiés <span className="text-brand-gold-dark">après</span> l&apos;arrivée. Les abonnés les reçoivent <span className="text-brand-gold-dark">avant le départ</span>.
                </p>
                <p className="mt-1 text-xs text-gray-600">
                  Paris de valeur, plan de mise et alertes en temps réel — dès 12€/mois, 7 jours d&apos;essai sans prélèvement.
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-center gap-3 sm:flex-row">
                <Link href="/track-record" className="text-xs font-semibold text-gray-600 underline underline-offset-2 hover:text-gray-900">
                  Voir nos performances
                </Link>
                <Link
                  href="/inscription"
                  className="press btn-shimmer inline-flex min-h-12 items-center gap-1.5 rounded-xl bg-brand-gold px-5 py-2.5 text-sm font-bold text-brand-dark shadow-lg shadow-amber-500/25 transition-colors hover:bg-brand-gold-deep"
                >
                  <Lock className="h-3.5 w-3.5" /> Recevoir les paris en direct <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          </Reveal>
        )}

        <p className="mx-auto mt-6 flex w-full max-w-2xl items-center justify-center gap-1.5 text-center text-[11px] text-gray-600">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-gray-600" />
          Paris réellement figés avant le départ puis réglés aux rapports PMU officiels — aucune reconstruction a posteriori. Parier comporte un risque de perte.
        </p>
      </div>
    </section>
  );
}
