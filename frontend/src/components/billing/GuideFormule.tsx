import Link from "next/link";
import { ArrowRight, CalendarDays, Crown, Sun, Target } from "lucide-react";

/**
 * « Quelle formule pour moi ? » — oriente selon la façon de jouer. Le calcul est
 * écrit en clair : dès deux semaines de jeu par mois, Expert (19 €) coûte moins
 * que deux Pass Semaine (24 €) ; le pass reste la bonne porte d'entrée pour un
 * jour ou une semaine isolés.
 */
const PROFILS = [
  {
    icone: Sun, qui: "Je joue un jour précis", exemple: "Le Quinté du dimanche, une grosse réunion",
    offre: "Pass Jour", prix: "5 €", detail: "24 h d'accès Expert, sans abonnement", href: "#passes",
  },
  {
    icone: CalendarDays, qui: "J'ai une semaine chargée", exemple: "Vacances, meeting, semaine de Quintés",
    offre: "Pass Semaine", prix: "12 €", detail: "7 jours d'accès Expert, sans abonnement", href: "#passes",
  },
  {
    icone: Crown, qui: "Je joue toutes les semaines", exemple: "Plusieurs réunions, tout au long du mois",
    offre: "Expert", prix: "19 €/mois", detail: "Moins cher que deux Pass Semaine (24 €). Résiliable à tout moment.",
    href: "#formules", vedette: true,
  },
  {
    icone: Target, qui: "Je suis quelques courses par jour", exemple: "Un budget serré, l'essentiel me suffit",
    offre: "Standard", prix: "12 €/mois", detail: "5 courses par jour avec classement et plan de mise", href: "#formules",
  },
];

export function GuideFormule() {
  return (
    <section aria-labelledby="titre-guide" className="mb-12 sm:mb-16">
      <div className="mb-6 text-center">
        <h2 id="titre-guide" className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">Quelle formule pour moi ?</h2>
        <p className="mt-1 text-sm text-muted-foreground">Choisissez selon votre façon de jouer : le bon prix suit.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PROFILS.map((p) => (
          <Link
            key={p.offre}
            href={p.href}
            className={
              p.vedette
                ? "group relative flex flex-col rounded-2xl bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 p-5 text-white ring-2 ring-amber-400/70 shadow-[0_24px_50px_-26px_rgba(6,78,59,.75)] transition-transform hover:-translate-y-1"
                : "group flex flex-col rounded-2xl bg-white p-5 ring-1 ring-stone-200 shadow-[0_18px_40px_-28px_rgba(17,24,39,.5)] transition-transform hover:-translate-y-1"
            }
          >
            {p.vedette && (
              <span className="absolute -top-3 left-5 rounded-full bg-gradient-to-b from-amber-300 to-amber-500 px-2.5 py-0.5 text-[11px] font-bold text-stone-900 shadow">
                Le plus avantageux
              </span>
            )}
            <span
              className={
                p.vedette
                  ? "flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 text-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.6),0_8px_16px_-8px_rgba(0,0,0,.5)]"
                  : "flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-b from-emerald-400 to-emerald-600 text-white shadow-[inset_0_1px_0_rgba(255,255,255,.6),0_8px_16px_-8px_rgba(0,0,0,.5)]"
              }
              aria-hidden
            >
              <p.icone className="h-5 w-5" />
            </span>
            <p className="mt-3 font-semibold leading-snug">{p.qui}</p>
            <p className={p.vedette ? "mt-0.5 text-xs text-stone-300" : "mt-0.5 text-xs text-muted-foreground"}>{p.exemple}</p>
            <div className={p.vedette ? "mt-4 border-t border-white/10 pt-3" : "mt-4 border-t border-stone-100 pt-3"}>
              <p className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-bold">{p.offre}</span>
                <span className={p.vedette ? "font-display text-xl font-extrabold text-amber-300" : "font-display text-xl font-extrabold"}>{p.prix}</span>
              </p>
              <p className={p.vedette ? "mt-1 text-xs text-stone-300" : "mt-1 text-xs text-muted-foreground"}>{p.detail}</p>
            </div>
            <span className={p.vedette ? "mt-3 inline-flex items-center gap-1 text-xs font-semibold text-amber-300" : "mt-3 inline-flex items-center gap-1 text-xs font-semibold text-emerald-700"}>
              Voir l&apos;offre <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
