import { ImageResponse } from "next/og";
import {
  fetchProgramme,
  fetchCourseDetail,
  jourParis,
  jourLong,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
} from "@/lib/seo";
import { TAILLE, COULEURS, MENTION_COURTE } from "@/lib/visuels";

// Le visuel change une fois par jour, quand le PMU désigne le support du Quinté+.
export const revalidate = 900;

/**
 * Visuel « Quinté+ du jour » — 1080×1080, prêt à publier.
 *
 * Tout ce qui figure dessus vient de l'API : hippodrome, discipline, distance, nombre de
 * partants, heure de départ. Aucune saisie manuelle, donc aucune coquille possible — et
 * produire le post du jour ne demande plus aucun travail.
 *
 * Le visuel ne porte AUCUN pronostic et AUCUN chiffre de gain. Une image qui circule hors
 * du site, sans son contexte, ne doit jamais pouvoir se lire comme une promesse.
 *
 * ATTENTION AU MOTEUR DE RENDU : Satori ne gère pas les fragments React (`<>…</>`) comme
 * enfants d'un conteneur flex — les éléments se superposent au lieu de s'empiler. Toute
 * la mise en page est donc construite avec des `div` explicites, chacun portant son
 * `display: "flex"`, et les branches conditionnelles renvoient des éléments entiers.
 */
export async function GET() {
  const jour = jourParis();
  const prog = await fetchProgramme(jour);

  let quinte = null;
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) quinte = c;
  }
  const detail = quinte ? await fetchCourseDetail(quinte.course_id) : null;
  const course = detail?.status === "ok" ? detail.course : quinte;

  const chips = course
    ? [
        codeReunionCourse(course.course_id),
        disciplineLabel(course.discipline),
        `${course.distance} m`,
        `${course.nb_partants} partants`,
        `Départ ${heureParis(course.date_heure)}`,
      ]
    : [];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: COULEURS.fond,
          padding: 72,
          fontFamily: "sans-serif",
        }}
      >
        {/* Bandeau haut : marque + date */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            width: "100%",
          }}
        >
          <div style={{ display: "flex", alignItems: "center" }}>
            <div style={{ display: "flex", width: 14, height: 44, background: COULEURS.or }} />
            <span style={{ color: COULEURS.encre, fontSize: 38, fontWeight: 700, marginLeft: 16 }}>
              BlackTurf
            </span>
          </div>
          <span style={{ color: COULEURS.encreDouce, fontSize: 26 }}>{jourLong(jour)}</span>
        </div>

        {/* Corps */}
        <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
          <span
            style={{
              color: COULEURS.or,
              fontSize: 30,
              fontWeight: 600,
              letterSpacing: 4,
            }}
          >
            QUINTÉ+ DU JOUR
          </span>

          <span
            style={{
              color: COULEURS.encre,
              fontSize: course && titleCase(course.hippodrome_nom).length > 14 ? 76 : 94,
              fontWeight: 800,
              lineHeight: 1.05,
              letterSpacing: -2,
              marginTop: 22,
            }}
          >
            {course ? titleCase(course.hippodrome_nom) : "Support pas encore publié"}
          </span>

          <span
            style={{
              color: COULEURS.encreDouce,
              fontSize: 36,
              lineHeight: 1.3,
              marginTop: 18,
            }}
          >
            {course
              ? titleCase(course.nom ?? "")
              : "Le PMU désigne la course la veille au soir."}
          </span>

          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 34 }}>
            {chips.map((t) => (
              <span
                key={t}
                style={{
                  display: "flex",
                  background: COULEURS.fondClair,
                  border: `2px solid ${COULEURS.ligne}`,
                  color: COULEURS.encre,
                  fontSize: 28,
                  padding: "12px 22px",
                  borderRadius: 8,
                  marginRight: 14,
                  marginBottom: 14,
                }}
              >
                {t}
              </span>
            ))}
          </div>
        </div>

        {/* Pied : adresse + mention */}
        <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
          <div style={{ display: "flex", height: 2, width: "100%", background: COULEURS.ligne }} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              width: "100%",
              marginTop: 20,
            }}
          >
            <span style={{ color: COULEURS.orVif, fontSize: 32, fontWeight: 600 }}>
              blackturf.fr/quinte-du-jour
            </span>
            <span
              style={{
                color: COULEURS.encreDouce,
                fontSize: 20,
                width: 400,
                textAlign: "right",
                lineHeight: 1.4,
              }}
            >
              {MENTION_COURTE}
            </span>
          </div>
        </div>
      </div>
    ),
    { width: TAILLE, height: TAILLE },
  );
}
