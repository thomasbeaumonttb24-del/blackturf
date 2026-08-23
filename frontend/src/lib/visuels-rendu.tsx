import { ImageResponse } from "next/og";
import {
  fetchProgramme,
  fetchCourseDetail,
  fetchResultats,
  jourParis,
  jourLong,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  type SeoCourse,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { TAILLE, COULEURS, MENTION_COURTE } from "@/lib/visuels";

/**
 * Fabrique des visuels sociaux 1080×1080 à partir des données réelles du jour.
 *
 * ─── DEUX CONTRAINTES QUI EXPLIQUENT LA FORME DE CE FICHIER ───
 *
 * 1. **Satori ne gère pas les fragments React (`<>…</>`) comme enfants d'un conteneur
 *    flex** : les éléments se superposent au lieu de s'empiler, sans la moindre erreur —
 *    le premier rendu était illisible. Toute la mise en page est donc faite de `div`
 *    explicites portant chacun `display: "flex"`, et les branches conditionnelles
 *    renvoient des éléments entiers.
 *
 * 2. **L'API de publication Instagram n'accepte que du JPEG.** `ImageResponse` ne produit
 *    que du PNG : on convertit derrière. La conversion est enveloppée — si elle échoue,
 *    on sert le PNG plutôt que de rendre la page studio inutilisable.
 *
 * Règle produit : ces visuels ne portent AUCUN pronostic et AUCUN chiffre de gain. Une
 * image circule hors de son contexte et ne doit jamais pouvoir se lire comme une promesse.
 */

async function quinteDuJour(jour: string): Promise<SeoCourse | null> {
  const prog = await fetchProgramme(jour);
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) return c;
  }
  return null;
}

function EnTete({ jour }: { jour: string }) {
  return (
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
  );
}

function PiedDePage({ adresse }: { adresse: string }) {
  return (
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
        <span style={{ color: COULEURS.orVif, fontSize: 32, fontWeight: 600 }}>{adresse}</span>
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
  );
}

const CADRE: React.CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
  background: COULEURS.fond,
  padding: 72,
  fontFamily: "sans-serif",
};

const PUCE: React.CSSProperties = {
  display: "flex",
  background: COULEURS.fondClair,
  border: `2px solid ${COULEURS.ligne}`,
  color: COULEURS.encre,
  borderRadius: 8,
  marginRight: 12,
  marginBottom: 12,
};

/** Visuel du matin : le support du Quinté+ du jour. */
export async function visuelQuinte(): Promise<ImageResponse> {
  const jour = jourParis();
  const resume = await quinteDuJour(jour);
  const detail = resume ? await fetchCourseDetail(resume.course_id) : null;
  const course = detail?.status === "ok" ? detail.course : resume;

  const puces = course
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
      <div style={CADRE}>
        <EnTete jour={jour} />

        <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
          <span style={{ color: COULEURS.or, fontSize: 30, fontWeight: 600, letterSpacing: 4 }}>
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
            style={{ color: COULEURS.encreDouce, fontSize: 36, lineHeight: 1.3, marginTop: 18 }}
          >
            {course
              ? titleCase(course.nom ?? "")
              : "Le PMU désigne la course la veille au soir."}
          </span>
          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 34 }}>
            {puces.map((t) => (
              <span key={t} style={{ ...PUCE, fontSize: 28, padding: "12px 22px" }}>
                {t}
              </span>
            ))}
          </div>
        </div>

        <PiedDePage adresse="blackturf.fr/quinte-du-jour" />
      </div>
    ),
    { width: TAILLE, height: TAILLE },
  );
}

/** Visuel du soir : arrivée officielle et rapports du Quinté+. */
export async function visuelArrivee(): Promise<ImageResponse> {
  const jour = jourParis();
  const quinte = await quinteDuJour(jour);
  const resultats = quinte ? await fetchResultats(quinte.course_id) : null;
  const classement = resultats?.classement?.slice(0, 5) ?? [];
  const rapports = rapportsTries(resultats?.rapports).slice(0, 4);
  const publiee = classement.length > 0;

  return new ImageResponse(
    (
      <div style={CADRE}>
        <EnTete jour={jour} />

        <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
          <span style={{ color: COULEURS.or, fontSize: 30, fontWeight: 600, letterSpacing: 4 }}>
            {publiee ? "ARRIVÉE DU QUINTÉ+" : "ARRIVÉE À VENIR"}
          </span>
          <span style={{ color: COULEURS.encreDouce, fontSize: 34, marginTop: 16 }}>
            {quinte ? titleCase(quinte.hippodrome_nom) : "Support du Quinté+ non publié"}
          </span>
          <span
            style={{
              color: COULEURS.encre,
              fontSize: publiee ? 88 : 52,
              fontWeight: 800,
              letterSpacing: publiee ? 4 : 0,
              lineHeight: 1.1,
              marginTop: 14,
            }}
          >
            {publiee
              ? classement.map((l) => l.numero).join(" - ")
              : "Rapports officiels pas encore publiés"}
          </span>

          <div style={{ display: "flex", flexDirection: "column", marginTop: 26 }}>
            {classement.map((l) => (
              <div
                key={l.position}
                style={{ display: "flex", alignItems: "center", marginBottom: 10 }}
              >
                <span
                  style={{
                    display: "flex",
                    width: 46,
                    height: 46,
                    alignItems: "center",
                    justifyContent: "center",
                    background: l.position === 1 ? COULEURS.or : COULEURS.fondClair,
                    color: l.position === 1 ? COULEURS.fond : COULEURS.encreDouce,
                    fontSize: 24,
                    fontWeight: 700,
                    borderRadius: 6,
                  }}
                >
                  {l.position}
                </span>
                <span style={{ color: COULEURS.encre, fontSize: 30, marginLeft: 18 }}>
                  n°{l.numero} {titleCase(l.nom)}
                </span>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", marginTop: 18 }}>
            {rapports.map(([code, val]) => (
              <span key={code} style={{ ...PUCE, fontSize: 24, padding: "10px 18px" }}>
                {libellePari(code)} {formatRapport(val)} €
              </span>
            ))}
          </div>
        </div>

        <PiedDePage adresse="blackturf.fr/resultats" />
      </div>
    ),
    { width: TAILLE, height: TAILLE },
  );
}

/**
 * Convertit un rendu `ImageResponse` (PNG) en JPEG.
 *
 * L'API de publication Instagram n'accepte QUE du JPEG. Si la conversion échoue — binaire
 * `sharp` absent de l'image de production, par exemple — on renvoie le PNG d'origine :
 * la page studio reste utilisable, seule la publication automatique serait à réparer.
 */
export async function enJpeg(rendu: ImageResponse): Promise<Response> {
  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(png)
      .flatten({ background: COULEURS.fond })
      .jpeg({ quality: 90, chromaSubsampling: "4:4:4" })
      .toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "public, max-age=300, s-maxage=300",
      },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: {
        "Content-Type": "image/png",
        "Cache-Control": "public, max-age=60",
      },
    });
  }
}
