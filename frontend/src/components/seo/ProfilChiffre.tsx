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

/** « le plat », « l'attelé » : sans l'article, la phrase disait « la discipline la plus
 *  courue y est plat ». L'élision suit la première lettre du libellé. */
const avecArticle = (label: string) => {
  const l = label.toLowerCase();
  return /^[aeiouâàéèêîïôùûh]/.test(l) ? `l'${l}` : `le ${l}`;
};

const euros = (n: number) => n.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Les douze derniers mois du lieu — la partie qui distingue vraiment deux fiches.
 *
 * Le volume et les distances décrivent une programmation ; ils ne disent pas ce qui s'y
 * passe. La part de courses gagnées par le favori du marché et le rapport gagnant médian,
 * si : entre 27 % à Chantilly et 44 % à Mons, ce n'est plus le même pari. Les deux
 * chiffres sortent de l'arrivée officielle et de la cote PMU au départ.
 *
 * Rien n'est affiché quand la mesure ne tient pas : sous trente courses cotées, un taux
 * de réussite n'est que du bruit, et le bloc disparaît plutôt que de meubler.
 */
function BlocRecent({
  p,
  lieu,
}: {
  p: { nb_courses_12m?: number; taux_favori?: number | null; rapport_gagnant_median?: number | null; nb_quintes_12m?: number };
  lieu?: string;
}) {
  const n = p.nb_courses_12m ?? 0;
  if (!n || (p.taux_favori == null && p.rapport_gagnant_median == null)) return null;

  return (
    <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50/40 p-4 sm:p-5">
      <p className="font-display text-[13px] font-semibold uppercase tracking-wide text-brand-gold-dark">
        Les douze derniers mois
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-amber-200 bg-amber-200 sm:grid-cols-3">
        {[
          { k: "Courses courues", v: fr(n) },
          p.taux_favori != null
            ? { k: "Courses gagnées par le favori", v: `${p.taux_favori.toLocaleString("fr-FR")} %` }
            : null,
          p.rapport_gagnant_median != null
            ? { k: "Rapport gagnant médian", v: `${euros(p.rapport_gagnant_median)} €` }
            : null,
        ]
          .filter((c): c is { k: string; v: string } => c !== null)
          .map((c) => (
            <div key={c.k} className="bg-white px-3.5 py-3">
              <dt className="text-[11px] leading-snug text-brand-charcoal">{c.k}</dt>
              <dd className="mt-1 font-display text-[18px] font-bold tabular-nums text-brand-dark">
                {c.v}
              </dd>
            </div>
          ))}
      </dl>
      <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
        Sur les {fr(n)} courses disputées {lieu ? `sur la piste ${lieu}` : "dans cette discipline"}{" "}
        depuis un an
        {p.taux_favori != null ? (
          <>
            , le favori du marché PMU l&apos;a emporté {p.taux_favori.toLocaleString("fr-FR")} fois sur
            cent. {p.taux_favori >= 35
              ? "C'est au-dessus de la moyenne française : la logique y est plutôt respectée, et les gros rapports s'y font rares."
              : p.taux_favori <= 30
                ? "C'est en dessous de la moyenne française : les favoris y tombent souvent, et l'outsider s'y défend mieux qu'ailleurs."
                : "C'est proche de la moyenne française, toutes disciplines confondues."}
          </>
        ) : (
          "."
        )}
        {p.rapport_gagnant_median != null && (
          <>
            {" "}Une course sur deux y a payé le gagnant au-dessus de {euros(p.rapport_gagnant_median)} €
            pour 1 € joué.
          </>
        )}
        {p.nb_quintes_12m ? (
          <>
            {" "}
            {fr(p.nb_quintes_12m)} Quinté+ y {p.nb_quintes_12m > 1 ? "ont été courus" : "a été couru"}{" "}
            sur la période.
          </>
        ) : null}
      </p>
    </div>
  );
}

/** Ceux qui gagnent sur place — une liste vraie, jamais un palmarès inventé. */
function BlocHommes({
  jockeys,
  entraineurs,
  lieu,
  monte,
}: {
  jockeys?: Array<{ nom: string; victoires: number }>;
  entraineurs?: Array<{ nom: string; victoires: number }>;
  lieu: string;
  monte: boolean;
}) {
  const j = (jockeys ?? []).slice(0, 5);
  const e = (entraineurs ?? []).slice(0, 5);
  if (!j.length && !e.length) return null;

  const colonne = (titre: string, gens: Array<{ nom: string; victoires: number }>) =>
    gens.length ? (
      <div>
        <p className="text-[13px] font-semibold text-brand-dark">{titre}</p>
        <ol className="mt-2 space-y-1.5">
          {gens.map((g, i) => (
            <li key={g.nom} className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-brand-charcoal">
                <span className="mr-2 tabular-nums text-[11px] text-brand-gold-dark">{i + 1}.</span>
                {g.nom}
              </span>
              <span className="shrink-0 tabular-nums text-[12.5px] font-medium text-brand-dark">
                {fr(g.victoires)} victoire{g.victoires > 1 ? "s" : ""}
              </span>
            </li>
          ))}
        </ol>
      </div>
    ) : null;

  return (
    <div className="mt-5 rounded-xl border border-gray-200 bg-white p-4 sm:p-5">
      <p className="font-display text-[13px] font-semibold uppercase tracking-wide text-brand-gold-dark">
        Qui gagne sur la piste {lieu}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-brand-charcoal">
        Les vainqueurs des douze derniers mois, comptés sur les arrivées officielles. Une
        spécialité locale se lit ici mieux que dans n&apos;importe quel classement national :
        un {monte ? "driver" : "jockey"} qui domine un hippodrome connaît sa piste.
      </p>
      <div className="mt-4 grid gap-5 sm:grid-cols-2">
        {colonne(monte ? "Drivers et jockeys" : "Jockeys", j)}
        {colonne("Entraîneurs", e)}
      </div>
    </div>
  );
}

export function ProfilChiffreLieu({
  nom,
  court,
  p,
}: {
  nom: string;
  /** Le nom sans son préfixe — « Vincennes » plutôt que « Hippodrome de Vincennes ». Les
   *  phrases l'emploient derrière « la piste de », qui évite les pièges d'accord de
   *  « à / au / aux » sur les seize fiches. */
  court?: string;
  p: ProfilLieu;
}) {
  const lieu = court || nom;
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
        BlackTurf a analysé {fr(p.nb_courses)} courses disputées sur la piste {lieu},
        réparties sur{" "}
        {fr(p.nb_journees)} journées.{" "}
        {principale && (
          <>
            La discipline la plus courue y est {avecArticle(disciplineLabel(principale[0]))}, avec{" "}
            {Math.round((principale[1] / total) * 100)} % des épreuves
            {disciplines.length > 1
              ? disciplines.length > 2
                ? ` — les ${disciplines.length - 1} autres se partagent le reste.`
                : " — l'autre discipline se partage le reste."
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

      <BlocRecent p={p} lieu={lieu} />

      <BlocHommes
        jockeys={p.top_jockeys}
        entraineurs={p.top_entraineurs}
        lieu={lieu}
        monte={(principale?.[0] ?? "").toUpperCase().includes("ATTEL")}
      />

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

      <BlocRecent p={p} />

      <p className="mt-4 text-[12px] leading-relaxed text-brand-charcoal">
        Chiffres établis sur l&apos;ensemble des courses de la base BlackTurf dont l&apos;arrivée a
        été publiée, et non sur une sélection.
      </p>
    </div>
  );
}
