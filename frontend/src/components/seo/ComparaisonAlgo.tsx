import Link from "next/link";
import { Trophy, Target, ShieldCheck } from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import type { SeoVerdict } from "@/lib/seo";

/**
 * Comparaison « algo vs arrivée » sur la page /resultats.
 *
 * Même règle d'intégrité que le reste du site (cf. `_PALMARES_INTEGRITE`
 * côté API) : chaque verdict vient d'un pronostic FIGÉ AVANT LE DÉPART
 * (`predictions.created_at < courses.date_heure`). Une course sans pronostic
 * archivé n'affiche simplement rien — jamais « le modèle s'est trompé » sur
 * une donnée qu'on n'a pas.
 */

const nomTitre = (s: string | null) =>
  s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";

const ordinal = (n: number) => `${n}${n === 1 ? "er" : "e"}`;

/** Bandeau de synthèse de la journée : deux chiffres, pas un tableau. C'est le
 *  même principe que `PreuvesRecentesCard` — le compteur AVANT les exemples,
 *  pour qu'on ne lise jamais la liste du dessous comme une vitrine triée. */
export function BilanAlgoJour({
  verdicts, nbCoursesJour,
}: {
  verdicts: SeoVerdict[];
  /** Total des arrivées publiées ce jour-là — pour dire honnêtement sur
   *  combien de courses le pronostic est vérifiable, pas seulement sur celles
   *  qui en avaient un. */
  nbCoursesJour: number;
}) {
  if (verdicts.length === 0) return null;
  const nTop1 = verdicts.filter((v) => v.gagnant_top1).length;
  const nTop3 = verdicts.filter((v) => v.gagnant_top3).length;

  return (
    <div className="mb-6 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_1px_2px_rgba(28,25,23,.04)]">
      <div className="flex items-center gap-2 border-b border-stone-100 bg-stone-50/70 px-4 py-3 sm:px-5">
        <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-800 ring-1 ring-amber-200">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <h2 className="font-display text-[14.5px] font-bold text-slate-900">
          Ce que l&apos;algorithme avait annoncé
        </h2>
      </div>

      <div className="grid gap-px bg-stone-100 sm:grid-cols-3">
        <div className="bg-white px-4 py-3.5 sm:px-5">
          <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-stone-600">
            <Trophy className="h-3 w-3 text-emerald-700" aria-hidden="true" /> Gagnants trouvés
          </p>
          <p className="mt-1 font-display text-[22px] font-bold tabular-nums text-emerald-700">
            {nTop1} <span className="text-[13px] font-normal text-stone-600">/ {verdicts.length}</span>
          </p>
          <p className="mt-0.5 text-[11px] text-stone-600">le favori du modèle a gagné</p>
        </div>

        <div className="bg-white px-4 py-3.5 sm:px-5">
          <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-stone-600">
            <Target className="h-3 w-3 text-amber-700" aria-hidden="true" /> Gagnants dans le top 3
          </p>
          <p className="mt-1 font-display text-[22px] font-bold tabular-nums text-amber-700">
            {nTop3} <span className="text-[13px] font-normal text-stone-600">/ {verdicts.length}</span>
          </p>
          <p className="mt-0.5 text-[11px] text-stone-600">le vainqueur figurait dans le podium annoncé</p>
        </div>

        <div className="bg-white px-4 py-3.5 sm:px-5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Pronostics vérifiables</p>
          <p className="mt-1 font-display text-[22px] font-bold tabular-nums text-slate-900">
            {verdicts.length} <span className="text-[13px] font-normal text-stone-600">/ {nbCoursesJour}</span>
          </p>
          <p className="mt-0.5 text-[11px] text-stone-600">
            courses avec un pronostic figé avant le départ
          </p>
        </div>
      </div>

      <p className="border-t border-stone-100 bg-stone-50/50 px-4 py-2.5 text-[11px] leading-4 text-stone-600 sm:px-5">
        Chaque comparaison ci-dessous vient d&apos;un pronostic calculé et enregistré{" "}
        <strong className="font-semibold text-slate-700">avant le départ</strong> — jamais reconstitué après
        l&apos;arrivée. Les courses ratées y figurent comme les autres.{" "}
        <Link href="/track-record" className="font-medium text-brand-gold-dark hover:underline">
          Voir le bilan complet →
        </Link>
      </p>
    </div>
  );
}

/** Ligne de comparaison insérée sous une arrivée : ce que le modèle avait
 *  joué favori, et où ce cheval a réellement terminé. Une seule phrase, un
 *  badge — la table détaillée (probabilités, cote juste, signaux) reste sur
 *  la fiche course, que ce badge relie. */
export function VerdictAlgoLigne({ v, courseId }: { v: SeoVerdict; courseId: string }) {
  const rang = v.rang_predit_gagnant;
  const ton = v.gagnant_top1
    ? { bg: "bg-emerald-50", fg: "text-emerald-700", ring: "ring-emerald-200/70", label: "Gagnant trouvé" }
    : v.gagnant_top3
      ? { bg: "bg-amber-50", fg: "text-amber-800", ring: "ring-amber-200/70", label: `Annoncé ${rang ? ordinal(rang) : "—"}` }
      : { bg: "bg-stone-100", fg: "text-stone-600", ring: "ring-stone-200", label: rang ? `Classé ${ordinal(rang)} par l'algo` : "Hors pronostic" };

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-brand-charcoal">
      <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-bold ring-1 ${ton.bg} ${ton.fg} ${ton.ring}`}>
        {ton.label}
      </span>
      {v.favori_numero != null && (
        <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
          <span className="whitespace-nowrap text-stone-600">Favori algo :</span>
          {/* Numéro seul sur téléphone : le nom, coupé à dix lettres, poussait
              la cote et la place d'arrivée sur deux lignes étroites. */}
          <CasaqueNumero numero={v.favori_numero} courseId={courseId} />
          <span className="hidden min-w-0 truncate sm:inline">{nomTitre(v.favori_nom)}</span>
          {v.favori_cote != null && (
            <span className="whitespace-nowrap text-stone-600">à {v.favori_cote.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</span>
          )}
          {!v.gagnant_top1 && v.favori_position != null && (
            <span className="whitespace-nowrap text-stone-600">→ arrivé {ordinal(v.favori_position)}</span>
          )}
        </span>
      )}
      <Link href={`/courses/${courseId}`} className="font-medium text-brand-gold-dark hover:underline">
        Voir le détail →
      </Link>
    </div>
  );
}
