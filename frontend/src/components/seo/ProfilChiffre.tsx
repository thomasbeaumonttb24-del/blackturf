import { disciplineLabel, type ProfilLieu, type ProfilDiscipline } from "@/lib/seo";

/**
 * Le profil chiffré d'un hippodrome ou d'une discipline, tiré de l'historique du site.
 *
 * Ces fiches ne portaient qu'un paragraphe d'introduction et le programme du jour :
 * 260 mots pour Vincennes, dont 171 propres à la page. Sur « hippodrome de vincennes »,
 * le site officiel et l'encyclopédie occupent le terrain avec de l'histoire et des
 * informations pratiques ; un texte d'introduction générique n'a aucune raison d'être
 * préféré à ceux-là.
 *
 * Ce que BlackTurf peut dire et qu'aucun d'eux ne dit : ce qui s'y court RÉELLEMENT —
 * combien de courses, dans quelles disciplines, sur quelles distances, avec quels
 * pelotons — mesuré sur la totalité de sa base. Des chiffres vérifiables, différents
 * d'une fiche à l'autre, tirés de données que le site possède déjà.
 *
 * Ce n'est pas du remplissage destiné à allonger la page : c'est la seule information
 * qu'un visiteur ne trouvera pas ailleurs.
 */
const fr = (n: number) => n.toLocaleString("fr-FR");

export function ProfilChiffreLieu({ nom, p }: { nom: string; p: ProfilLieu }) {
  const disciplines = Object.entries(p.disciplines);
  const total = disciplines.reduce((s, [, n]) => s + n, 0) || 1;
  const principale = disciplines[0];

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 sm:p-6">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-gray-200 bg-gray-200 sm:grid-cols-4">
        {[
          { k: "Courses analysées", v: fr(p.nb_courses) },
          { k: "Journées de courses", v: fr(p.nb_journees) },
          {
            k: "Distances",
            v:
              p.distance_min && p.distance_max
                ? p.distance_min === p.distance_max
                  ? `${fr(p.distance_min)} m`
                  : `${fr(p.distance_min)}–${fr(p.distance_max)} m`
                : "—",
          },
          { k: "Partants en moyenne", v: p.partants_moyen.toLocaleString("fr-FR") },
        ].map((c) => (
          <div key={c.k} className="bg-white px-3.5 py-3">
            <dt className="text-[11px] leading-snug text-brand-charcoal">{c.k}</dt>
            <dd className="mt-1 font-display text-[18px] font-bold tabular-nums text-brand-dark">
              {c.v}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
        BlackTurf a analysé {fr(p.nb_courses)} courses disputées à {nom}, réparties sur{" "}
        {fr(p.nb_journees)} journées.{" "}
        {principale && (
          <>
            La discipline la plus courue y est {disciplineLabel(principale[0]).toLowerCase()}, avec{" "}
            {Math.round((principale[1] / total) * 100)} % des épreuves
            {disciplines.length > 1
              ? ` — les ${disciplines.length - 1} autre${disciplines.length > 2 ? "s" : ""} se partagent le reste.`
              : "."}{" "}
          </>
        )}
        La distance moyenne y est de {fr(p.distance_moyenne)} mètres, pour des pelotons de{" "}
        {p.partants_moyen.toLocaleString("fr-FR")} partants en moyenne.
      </p>

      {disciplines.length > 1 && (
        <ul className="mt-4 flex flex-wrap gap-2">
          {disciplines.map(([d, n]) => (
            <li
              key={d}
              className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-[12.5px] text-brand-charcoal"
            >
              <span className="font-medium text-brand-dark">{disciplineLabel(d)}</span>{" "}
              {Math.round((n / total) * 100)} %
            </li>
          ))}
        </ul>
      )}

      <p className="mt-4 text-[12px] leading-relaxed text-brand-charcoal">
        Chiffres établis sur l&apos;ensemble des courses de la base BlackTurf dont l&apos;arrivée a
        été publiée, et non sur une sélection.
      </p>
    </div>
  );
}

export function ProfilChiffreDiscipline({ nom, p }: { nom: string; p: ProfilDiscipline }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 sm:p-6">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-gray-200 bg-gray-200 sm:grid-cols-4">
        {[
          { k: "Courses analysées", v: fr(p.nb_courses) },
          { k: "Hippodromes concernés", v: fr(p.nb_hippodromes) },
          {
            k: "Distances",
            v:
              p.distance_min && p.distance_max
                ? `${fr(p.distance_min)}–${fr(p.distance_max)} m`
                : "—",
          },
          { k: "Partants en moyenne", v: p.partants_moyen.toLocaleString("fr-FR") },
        ].map((c) => (
          <div key={c.k} className="bg-white px-3.5 py-3">
            <dt className="text-[11px] leading-snug text-brand-charcoal">{c.k}</dt>
            <dd className="mt-1 font-display text-[18px] font-bold tabular-nums text-brand-dark">
              {c.v}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
        {fr(p.nb_courses)} courses {nom.toLowerCase()} figurent dans la base BlackTurf, courues sur{" "}
        {fr(p.nb_hippodromes)} hippodromes. La distance moyenne y est de{" "}
        {fr(p.distance_moyenne)} mètres
        {p.distance_min && p.distance_max
          ? ` — de ${fr(p.distance_min)} à ${fr(p.distance_max)} mètres selon l'épreuve`
          : ""}
        , pour {p.partants_moyen.toLocaleString("fr-FR")} partants en moyenne. Le nombre de
        partants pèse directement sur les rapports : plus le peloton est fourni, plus une
        combinaison exacte devient improbable — et mieux elle paie.
      </p>

      <p className="mt-4 text-[12px] leading-relaxed text-brand-charcoal">
        Chiffres établis sur l&apos;ensemble des courses de la base BlackTurf dont l&apos;arrivée a
        été publiée, et non sur une sélection.
      </p>
    </div>
  );
}
