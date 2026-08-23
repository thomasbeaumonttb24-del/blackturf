import { ImageResponse } from "next/og";
import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  jourLong,
  titleCase,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { TAILLE, COULEURS, MENTION_COURTE } from "@/lib/visuels";

export const revalidate = 300;

/**
 * Visuel « Arrivée du Quinté+ » — 1080×1080, publiable dès les rapports publiés.
 *
 * Le post du soir est le seul qui se partage vraiment : tout le monde cherche l'arrivée,
 * et elle est vérifiable. On n'y met que du fait — classement et rapports officiels —
 * jamais un commentaire sur ce que « le modèle avait vu » : une image qui circule hors du
 * site, sans son contexte, ne doit pas pouvoir se lire comme une promesse de gain.
 *
 * Satori ne gère pas les fragments React comme enfants d'un flex : toute la mise en page
 * est faite de `div` explicites (cf. le commentaire détaillé dans visuels/quinte).
 */
export async function GET() {
  const jour = jourParis();
  const prog = await fetchProgramme(jour);

  let quinte = null;
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) quinte = c;
  }
  const resultats = quinte ? await fetchResultats(quinte.course_id) : null;
  const classement = resultats?.classement?.slice(0, 5) ?? [];
  const rapports = rapportsTries(resultats?.rapports).slice(0, 4);
  const publiee = classement.length > 0;

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
              <span
                key={code}
                style={{
                  display: "flex",
                  background: COULEURS.fondClair,
                  border: `2px solid ${COULEURS.ligne}`,
                  color: COULEURS.encre,
                  fontSize: 24,
                  padding: "10px 18px",
                  borderRadius: 8,
                  marginRight: 12,
                  marginBottom: 12,
                }}
              >
                {libellePari(code)} {formatRapport(val)} €
              </span>
            ))}
          </div>
        </div>

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
              blackturf.fr/resultats
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
