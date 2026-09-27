"use client";

/* Vue NON ABONNÉE de la fiche course, calquée carte pour carte sur celle de
   l'abonné (onglets Synthèse et Partants). Le visiteur voit la même page, les
   mêmes jauges et les mêmes chiffres agrégés — tous déjà servis par l'aperçu
   public `/courses/{id}/apercu` — et ce qui reste payant (le nom des chevaux
   du haut du classement, l'analyse rédigée) est dessiné en formes neutres.
   Aucune donnée n'est déduite ici : si l'aperçu ne l'envoie pas, elle n'est
   pas affichée. */

import { Brain, Lock, Sparkles } from "lucide-react";
import type { ApercuAnalyse } from "@/components/courses/insights";
import {
  Anneau, AnneauVerrouille, BoutonAbonnement, CARTE_CLS, IconeTuile, IdentiteMasquee,
  PastilleReserve, SG, Squelette, VoileAbonne, lienAbonnement,
} from "@/components/courses/course-ui";
import { cn } from "@/lib/utils";

/** Les quatre cartes de tête de l'onglet Synthèse, version aperçu. */
export function StatsApercu({ apercu, nbPartants, connecte }: {
  apercu: ApercuAnalyse;
  nbPartants: number;
  connecte: boolean;
}) {
  const lien = lienAbonnement(connecte);
  const nbVB = apercu.nb_value_bets;
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-4">
      {/* Favori algo — la jauge est la vraie probabilité du n°1, son nom est réservé */}
      <a href={lien.href} className={cn(CARTE_CLS, "cx-fade group block bg-gradient-to-br from-amber-50/80 via-white to-white p-3.5 transition-transform hover:-translate-y-0.5 sm:p-4")} style={{ animationDelay: ".04s" }}>
        <p className="m-0 flex items-center justify-between text-[10.5px] font-bold uppercase tracking-[.1em] text-amber-700">
          Favori algo <Lock className="h-3 w-3" aria-hidden="true" />
        </p>
        <IdentiteMasquee className="mt-2" largeur="7rem" />
        <div className="mt-2.5 flex items-center gap-2.5">
          {apercu.proba_top1 != null ? <Anneau v={apercu.proba_top1} rang={1} taille={48} /> : <AnneauVerrouille taille={48} />}
          <span className="text-[11.5px] leading-snug text-stone-500">
            victoire
            {apercu.bande_cote ? <><br />coté <b className="font-bold text-stone-800">{apercu.bande_cote}</b></> : null}
          </span>
        </div>
        <span className="mt-2 block text-[11.5px] font-semibold text-amber-800 group-hover:underline">Découvrir son nom ›</span>
      </a>

      {/* Pari de valeur — combien, et la meilleure espérance (arrondie à 5 % par le serveur) */}
      <a
        href={nbVB > 0 ? lien.href : undefined}
        className={cn(CARTE_CLS, "cx-fade group block p-3.5 sm:p-4", nbVB > 0 && "bg-gradient-to-br from-emerald-50/80 via-white to-white transition-transform hover:-translate-y-0.5")}
        style={{ animationDelay: ".08s" }}
      >
        <p className={cn("m-0 flex items-center justify-between text-[10.5px] font-bold uppercase tracking-[.1em]", nbVB > 0 ? "text-emerald-700" : "text-stone-500")}>
          Pari de valeur {nbVB > 0 && <Lock className="h-3 w-3" aria-hidden="true" />}
        </p>
        {nbVB > 0 ? (
          <>
            <IdentiteMasquee className="mt-2" largeur="7rem" />
            <div className="mt-2 flex flex-wrap items-baseline gap-x-1.5">
              {apercu.ev_max_pct != null && (
                <span className="text-[26px] font-bold leading-none text-emerald-700" style={SG}>+{apercu.ev_max_pct}%</span>
              )}
              <span className="text-[11px] text-stone-500">
                {apercu.ev_max_pct != null ? "espérance" : ""}{nbVB > 1 ? ` · ${nbVB} détectés` : ""}
              </span>
            </div>
            <span className="mt-2 block text-[11.5px] font-semibold text-emerald-800 group-hover:underline">Voir le cheval ›</span>
          </>
        ) : (
          <p className="m-0 mt-2 text-[12px] leading-snug text-stone-500">Aucun pari de valeur détecté sur cette course.</p>
        )}
      </a>

      {/* Accord des modèles — même chiffre que la fiche abonné */}
      <div className={cn(CARTE_CLS, "cx-fade p-3.5 sm:p-4")} style={{ animationDelay: ".12s" }}>
        <p className="m-0 text-[10.5px] font-bold uppercase tracking-[.1em] text-stone-500">Accord des modèles</p>
        {apercu.confiance != null ? (
          <>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-[26px] font-bold leading-none text-emerald-700" style={SG}>{Math.round(apercu.confiance)}</span>
              <span className="text-[11px] text-stone-500">/ 100 · sur son n°1</span>
            </div>
            <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.08)]">
              <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, Math.round(apercu.confiance)))}%`, borderRadius: 999, background: "linear-gradient(90deg,#F59E0B,#059669)", transformOrigin: "left", animation: "cxBarGrow .7s cubic-bezier(.16,1,.3,1) .3s both" }} />
            </div>
          </>
        ) : <p className="m-0 mt-2 text-[12px] text-stone-500">—</p>}
      </div>

      {/* Le champ */}
      <div className={cn(CARTE_CLS, "cx-fade p-3.5 sm:p-4")} style={{ animationDelay: ".16s" }}>
        <p className="m-0 text-[10.5px] font-bold uppercase tracking-[.1em] text-stone-500">Le champ</p>
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className="text-[26px] font-bold leading-none text-stone-900" style={SG}>{nbPartants}</span>
          <span className="text-[11px] text-stone-500">partants</span>
        </div>
        <p className="m-0 mt-2 text-[11.5px] text-stone-500">
          {nbPartants >= 14 ? "Champ ouvert" : nbPartants >= 10 ? "Champ moyen" : "Petit champ"}
          {apercu.nb_ecartes > 0 ? ` · ${apercu.nb_ecartes} écartés sous 3 %` : ""}
        </p>
      </div>
    </div>
  );
}

/** Carte « Analyse BlackTurf » de l'abonné, contenu réservé. Le décor sous le
 *  voile ne reprend que la FORME de la carte (puces, encadré de conclusion,
 *  pastilles) : aucun mot de l'analyse n'est chargé ni affiché. */
export function AnalyseVerrouillee({ connecte }: { connecte: boolean }) {
  const ligne = (label: string, w: string) => (
    <div className="flex items-center gap-2.5 py-0.5">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400/70" />
      <span className="shrink-0 text-[13px] font-bold text-stone-800">{label}</span>
      <Squelette largeur={w} />
    </div>
  );
  return (
    <section className={cn(CARTE_CLS, "p-4 sm:p-5")}>
      <header className="mb-3 flex items-center gap-2">
        <IconeTuile icone={Brain} />
        <h3 className="m-0 text-[15px] font-bold text-stone-900" style={SG}>Analyse BlackTurf</h3>
        <PastilleReserve className="ml-auto" libelle="Standard" />
      </header>
      <VoileAbonne
        icone={Sparkles}
        titre="L'analyse rédigée de cette course"
        texte="Le favori expliqué, la conclusion du modèle, les chevaux à surveiller et les outsiders à tenter — chacun avec ses motifs chiffrés."
        action={<BoutonAbonnement connecte={connecte} />}
        decor={
          <div className="space-y-2.5 py-1">
            {ligne("Favori IA", "62%")}
            {ligne("Lecture", "78%")}
            <div className="flex items-center gap-2.5 rounded-xl bg-amber-50/70 px-3 py-2.5">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400/70" />
              <span className="shrink-0 text-[13px] font-bold text-stone-800">Conclusion</span>
              <Squelette largeur="70%" />
            </div>
            {ligne("À surveiller", "54%")}
            <div className="flex flex-wrap gap-1.5 border-t border-stone-100 pt-3">
              {["6rem", "7.5rem", "5rem"].map((w) => (
                <span key={w} className="h-6 rounded-full bg-amber-50 ring-1 ring-amber-200" style={{ width: w }} />
              ))}
            </div>
          </div>
        }
      />
    </section>
  );
}
