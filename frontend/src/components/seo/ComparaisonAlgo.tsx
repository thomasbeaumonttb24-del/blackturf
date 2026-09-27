import Link from "next/link";
import { Trophy, Target, ShieldCheck, Sparkles } from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import type { SeoVerdict, SeoPronoCheval } from "@/lib/seo";

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
          <span className="hidden min-w-0 sm:inline">{nomTitre(v.favori_nom)}</span>
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

/* ───────────── Top 5 de l'algorithme sous une arrivée ─────────────
 * Les cinq chevaux que le modèle classait en tête AVANT le départ, dans son ordre,
 * chacun avec sa place réelle. Le lecteur lit d'un coup d'œil ce qui était annoncé
 * et ce qui est arrivé, sans aller sur la fiche course. */

/** Médaille de rang : or, argent, bronze, puis ardoise. Dégradé + reflet + ombre
 *  portée pour le relief. */
const MEDAILLE: Record<number, string> = {
  1: "from-amber-200 via-amber-400 to-amber-600 text-amber-950 ring-amber-300/70",
  2: "from-slate-100 via-slate-300 to-slate-500 text-slate-900 ring-slate-200/70",
  3: "from-orange-200 via-orange-400 to-orange-700 text-orange-950 ring-orange-300/70",
};
const MEDAILLE_AUTRE = "from-slate-500 via-slate-600 to-slate-800 text-white ring-slate-400/40";

/** Ce qu'est devenu le cheval à l'arrivée, en pastille. */
function issue(position: number | null) {
  if (position === 1)
    return { label: "Gagnant", court: "1er", cls: "bg-gradient-to-b from-emerald-400 to-emerald-600 text-white shadow-[0_2px_0_#047857]" };
  if (position === 2 || position === 3)
    return { label: `Arrivé ${ordinal(position)}`, court: ordinal(position), cls: "bg-gradient-to-b from-amber-300 to-amber-500 text-amber-950 shadow-[0_2px_0_#b45309]" };
  if (position === 4 || position === 5)
    return { label: `Arrivé ${ordinal(position)}`, court: ordinal(position), cls: "bg-gradient-to-b from-sky-100 to-sky-200 text-sky-900 shadow-[0_2px_0_#7dd3fc]" };
  return {
    label: position != null ? `${ordinal(position)}` : "Non placé",
    court: position != null ? `${ordinal(position)}` : "NP",
    cls: "bg-stone-100 text-stone-500 shadow-[0_2px_0_#d6d3d1]",
  };
}

const pct = (p: number) =>
  `${(p * 100).toLocaleString("fr-FR", { maximumFractionDigits: p < 0.1 ? 1 : 0 })} %`;

export function PronosticAlgoTop5({ v, courseId }: { v: SeoVerdict; courseId: string }) {
  const top = (v.top5 ?? []).slice(0, 5);
  if (top.length === 0) return <VerdictAlgoLigne v={v} courseId={courseId} />;

  const dansLes5 = top.filter((h) => h.position != null && h.position <= 5).length;
  const probaMax = Math.max(...top.map((h) => h.proba ?? 0), 0.0001);
  const rang = v.rang_predit_gagnant;
  const verdict = v.gagnant_top1
    ? { label: "Gagnant trouvé", cls: "bg-emerald-400/15 text-emerald-300 ring-emerald-400/40" }
    : rang != null && rang <= 5
      ? { label: `Vainqueur annoncé ${ordinal(rang)}`, cls: "bg-amber-400/15 text-amber-300 ring-amber-400/40" }
      : { label: rang ? `Vainqueur classé ${ordinal(rang)} par l'algo` : "Vainqueur hors pronostic", cls: "bg-white/10 text-slate-300 ring-white/20" };

  return (
    <section
      aria-label="Pronostic de l'algorithme — top 5"
      className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-800 via-slate-900 to-[#0b1120] p-3 text-white shadow-[0_18px_30px_-18px_rgba(15,23,42,.8),inset_0_1px_0_rgba(255,255,255,.08)] ring-1 ring-slate-900/60 sm:p-4"
    >
      {/* halo doré discret en haut à droite */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-20 h-44 w-44 rounded-full bg-amber-400/20 blur-3xl"
      />

      <header className="relative flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 text-amber-950 shadow-[0_3px_0_#92400e,0_6px_12px_-4px_rgba(245,158,11,.6)]">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="font-display text-[14px] font-bold leading-tight">Pronostic de l&apos;algorithme</h3>
            <p className="text-[10.5px] leading-tight text-slate-400">Top 5 figé avant le départ</p>
          </div>
        </div>
        <span className="inline-flex items-baseline gap-1 rounded-full bg-white/10 px-2.5 py-1 text-[11px] text-slate-300 ring-1 ring-white/15">
          <strong className="font-display text-[14px] font-bold tabular-nums text-white">{dansLes5}/5</strong>
          dans les 5 premiers
        </span>
      </header>

      <ol className="relative mt-3 space-y-2">
        {top.map((h) => (
          <LignePronostic key={h.numero} h={h} courseId={courseId} probaMax={probaMax} />
        ))}
      </ol>

      <footer className="relative mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold ring-1 ${verdict.cls}`}>
          {verdict.label}
        </span>
        <Link
          href={`/courses/${courseId}`}
          className="text-[11.5px] font-semibold text-amber-300 hover:text-amber-200 hover:underline"
        >
          Analyse complète →
        </Link>
      </footer>
    </section>
  );
}

function LignePronostic({ h, courseId, probaMax }: { h: SeoPronoCheval; courseId: string; probaMax: number }) {
  const res = issue(h.position);
  const gagnant = h.position === 1;
  const cote =
    h.cote != null ? h.cote.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : null;

  return (
    <li
      className={`flex items-center gap-2 rounded-xl bg-gradient-to-b from-white to-stone-100 px-2 py-2 text-slate-900 transition-transform duration-200 hover:-translate-y-0.5 sm:gap-3 sm:px-2.5 ${
        gagnant
          ? "shadow-[0_3px_0_#059669,0_0_22px_-2px_rgba(52,211,153,.55)] ring-2 ring-emerald-400"
          : "shadow-[0_3px_0_#cbd5e1,0_10px_18px_-10px_rgba(0,0,0,.7)]"
      }`}
    >
      {/* médaille de rang */}
      <span
        aria-label={`Rang ${h.rang} du pronostic`}
        className={`relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-display text-[14px] font-extrabold ring-2 shadow-[inset_0_2px_2px_rgba(255,255,255,.55),inset_0_-2px_3px_rgba(0,0,0,.25),0_3px_6px_-1px_rgba(0,0,0,.35)] ${
          MEDAILLE[h.rang] ?? MEDAILLE_AUTRE
        }`}
      >
        {h.rang}
      </span>

      <CasaqueNumero numero={h.numero} courseId={courseId} />

      <div className="min-w-0 flex-1">
        {/* Nom entier, sur deux lignes au besoin : tronqué, il tombait à six
            lettres sur téléphone (« Joyeus… »). */}
        <p className="break-words text-[13px] font-bold leading-tight">
          {nomTitre(h.nom) || `N°${h.numero}`}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {h.proba != null && (
            <span
              className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-stone-200 shadow-[inset_0_1px_1px_rgba(0,0,0,.15)] sm:w-20"
              aria-hidden="true"
            >
              <span
                className="block h-full rounded-full bg-gradient-to-r from-amber-400 to-amber-600"
                style={{ width: `${Math.max(6, (h.proba / probaMax) * 100)}%` }}
              />
            </span>
          )}
          <span className="whitespace-nowrap text-[10.5px] tabular-nums text-stone-500">
            {h.proba != null && <>{pct(h.proba)}<span className="hidden sm:inline"> de victoire</span></>}
            {h.proba != null && cote && " · "}
            {cote && <>cote {cote}</>}
          </span>
        </div>
      </div>

      <span
        className={`inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-bold tabular-nums ${res.cls}`}
      >
        {gagnant && <Trophy className="h-3 w-3" aria-hidden="true" />}
        {/* « Arrivé 3e » prenait sur téléphone toute la place du nom. */}
        <span className="sm:hidden" title={res.label}>{res.court}</span>
        <span className="hidden sm:inline">{res.label}</span>
      </span>
    </li>
  );
}
