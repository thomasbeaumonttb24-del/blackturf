"use client";

/**
 * Ligne « Quinté+ » du palmarès — décision du 2026-09-24.
 *
 * Le ticket Quinté+ est joué sur chaque course Quinté+, par les trois profils,
 * avec de l'argent réel. Son rendement se montre ICI, sur sa propre ligne, et
 * n'entre dans aucun autre total de la page : un gros rapport de Quinté+ ne doit
 * jamais maquiller le rendement du plan principal (ni l'inverse).
 *
 * Source : `quinte` de `/stats/palmares-public` (et de la version admin), calculé
 * par `api/routes/stats._quinte_palmares` sur les plans figés avant le départ et
 * réglés aux rapports PMU. Tant qu'aucun ticket n'est réglé, on affiche « premiers
 * résultats à venir » — jamais un chiffre inventé.
 */

import { Trophy } from "lucide-react";

export interface QuintePalmaresData {
  disponible: boolean;
  nb_tickets: number;
  nb_courses: number;
  nb_en_attente: number;
  // Montants et ROI : vue admin seulement (le public ne reçoit que les comptages).
  mise_totale?: number;
  retour?: number;
  net?: number;
  roi?: number | null;
  nb_tickets_gagnants: number;
  nb_bonus: number;
  nb_cinq_sur_cinq: number;
  depuis?: string | null;
}

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const eur = (n: number) => `${nf(n, n % 1 === 0 ? 0 : 2)} €`;

function Chiffre({ label, value, sub, ton }: { label: string; value: string; sub?: string; ton?: string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-stone-50 px-4 py-3 ring-1 ring-stone-200/80">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 font-display text-2xl font-black tabular-nums ${ton ?? "text-slate-900"}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{sub}</p>}
    </div>
  );
}

export function QuinteLigne({ quinte }: { quinte?: QuintePalmaresData | null }) {
  const pret = !!quinte?.disponible && quinte.nb_tickets > 0;
  return (
    <section aria-label="Quinté+, compté à part" className="rounded-3xl bg-white p-5 ring-1 ring-stone-200 sm:p-7">
      <div className="flex items-start gap-3">
        <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-amber-300">
          <Trophy className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 className="font-display text-lg font-bold text-slate-900">Quinté+ · compté à part</h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Sur chaque course Quinté+, chaque profil joue aussi un ticket Quinté+ (2 € la combinaison).
            Ses résultats sont sur cette ligne seulement : ils n&apos;entrent dans aucun autre total de cette page.
          </p>
        </div>
      </div>

      {!pret ? (
        <p className="mt-5 rounded-2xl bg-stone-50 px-4 py-4 text-sm font-semibold text-slate-800 ring-1 ring-stone-200/80">
          Premiers résultats à venir
          <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">
            Ils s&apos;afficheront ici dès que les premiers tickets Quinté+ seront réglés aux rapports officiels
            {quinte && quinte.nb_en_attente > 0
              ? ` (${nf(quinte.nb_en_attente)} ticket${quinte.nb_en_attente > 1 ? "s" : ""} en attente d'un rapport PMU).`
              : "."}
          </span>
        </p>
      ) : (
        <>
          <div className={`mt-5 grid grid-cols-2 gap-3 ${quinte!.mise_totale != null ? "lg:grid-cols-5" : "lg:grid-cols-3"}`}>
            <Chiffre label="Tickets" value={nf(quinte!.nb_tickets)}
              sub={`sur ${nf(quinte!.nb_courses)} course${quinte!.nb_courses > 1 ? "s" : ""} Quinté+`} />
            {quinte!.mise_totale != null && <Chiffre label="Mise totale" value={eur(quinte!.mise_totale)} />}
            {quinte!.retour != null ? (
              <Chiffre label="Retour" value={eur(quinte!.retour)}
                sub={`${nf(quinte!.nb_tickets_gagnants)} ticket${quinte!.nb_tickets_gagnants > 1 ? "s" : ""} avec un retour`} />
            ) : (
              <Chiffre label="Tickets avec un retour" value={nf(quinte!.nb_tickets_gagnants)} />
            )}
            {quinte!.roi !== undefined && (
              <Chiffre label="ROI" value={quinte!.roi == null ? "—" : `${quinte!.roi > 0 ? "+" : ""}${nf(quinte!.roi, 1)} %`}
                ton={quinte!.roi != null && quinte!.roi >= 0 ? "text-emerald-700" : "text-rose-700"} />
            )}
            <Chiffre label="Bonus" value={nf(quinte!.nb_bonus)}
              sub={`combinaison${quinte!.nb_bonus > 1 ? "s" : ""} payée${quinte!.nb_bonus > 1 ? "s" : ""} en Bonus · ${nf(quinte!.nb_cinq_sur_cinq)} aux 5 premiers`} />
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Tickets des plans figés avant le départ (plan de référence de 10 €), réglés aux rapports PMU officiels,
            Bonus 4sur5 et Bonus 3 compris.
            {quinte!.nb_en_attente > 0 && ` ${nf(quinte!.nb_en_attente)} ticket${quinte!.nb_en_attente > 1 ? "s" : ""} en attente d'un rapport, non compté${quinte!.nb_en_attente > 1 ? "s" : ""}.`}
            {" "}Un Quinté+ se court une fois par jour : l&apos;échantillon reste petit, et aucune espérance de gain positive
            n&apos;est établie pour un Quinté+ joué systématiquement.
          </p>
        </>
      )}
    </section>
  );
}
