import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";

/**
 * Trois formules seulement — gratuit, essai sans abonnement, recommandée — et les
 * autres en une ligne. Partagé par l'accueil et /decouvrir. Contenu aligné sur la
 * grille de /tarifs (quotas réels du backend).
 */
export function FormulesSimples({ inscription, id, tutoiement = false }: { inscription: string; id?: string; tutoiement?: boolean }) {
  const formules = [
    { nom: "Gratuit", prix: "0 €", sous: "pour toujours", points: ["Programme et cotes en direct", "1 course analysée par jour", "Défi du mois"], cta: "Créer un compte", href: inscription, fort: false },
    { nom: "Pass Jour", prix: "5 €", sous: "24 h, sans abonnement", points: ["Tout débloqué pendant 24 h", "Aucun renouvellement", "Idéal un jour de Quinté+"], cta: "Tester 24 h", href: "/tarifs#passes", fort: false },
    { nom: "Expert", prix: "19 €", sous: "par mois, sans engagement", points: ["Toutes les courses, sans limite", "Paris de valeur en direct", "Assistant IA et alertes"], cta: "Passer Expert", href: "/tarifs", fort: true },
  ];
  return (
    <section id={id} className="scroll-mt-20 border-t border-stone-200 bg-[#faf8f4]">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-brand-gold-dark">Formules</p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.025em] text-stone-950 sm:text-4xl">{tutoiement ? "Commence gratuitement. Débloque tout quand tu veux." : "Commencez gratuitement. Débloquez tout quand vous voulez."}</h2>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {formules.map((f) => (
            <div
              key={f.nom}
              className={`flex flex-col rounded-2xl p-7 ${f.fort ? "bg-stone-950 text-white" : "bg-white ring-1 ring-stone-200"}`}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-[15px] font-semibold">{f.nom}</h3>
                {f.fort && <span className="text-xs font-medium text-amber-400">Recommandé</span>}
              </div>
              <div className="mt-5 flex items-baseline gap-2">
                <span className="font-display text-5xl font-semibold tracking-tight tabular-nums">{f.prix}</span>
                <span className={`text-sm ${f.fort ? "text-stone-400" : "text-stone-500"}`}>{f.sous}</span>
              </div>
              <ul className={`mt-7 space-y-3 border-t pt-6 ${f.fort ? "border-stone-800" : "border-stone-200"}`}>
                {f.points.map((p) => (
                  <li key={p} className="flex items-start gap-2.5 text-[15px]">
                    <Check className={`mt-0.5 h-4 w-4 shrink-0 ${f.fort ? "text-amber-400" : "text-stone-900"}`} />
                    <span className={f.fort ? "text-stone-200" : "text-stone-600"}>{p}</span>
                  </li>
                ))}
              </ul>
              <Link
                href={f.href}
                className={`mt-8 inline-flex items-center justify-center gap-2 rounded-full px-5 py-3 text-[15px] font-semibold transition-colors ${
                  f.fort ? "bg-white text-stone-950 hover:bg-stone-200" : "bg-stone-950 text-white hover:bg-stone-800"
                }`}
              >
                {f.cta} <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          ))}
        </div>
        <p className="mt-6 text-sm text-stone-500">
          Aussi : Standard 12 €/mois, Pass Semaine 12 €, Pass Mois 24 €.{" "}
          <Link href="/tarifs" className="font-medium text-stone-900 underline underline-offset-4">Tous les prix</Link>
        </p>
      </div>
    </section>
  );
}
