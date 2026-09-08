import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { imageEnDataUri } from "@/lib/mosaique";

/**
 * Générateur de la vignette de partage — `public/og-image.jpg`.
 *
 * ─────────────────────────── POURQUOI UN GÉNÉRATEUR ────────────────────────────────────
 *
 * La vignette précédente était un bloc de texte fabriqué à la main : aucun logo, des
 * accents manquants dans l'image elle-même (« personnalise », « detectes »,
 * « reentraine ») — impossibles à corriger sans refaire le fichier, et affichés tels
 * quels par Safari, iMessage, WhatsApp, LinkedIn et l'aperçu de Google. C'est la
 * première image que voit un prospect qui n'a jamais ouvert le site.
 *
 * Elle est donc DÉCRITE ici, avec les polices et la charte du site, et le fichier servi
 * reste STATIQUE : un crawler qui prépare un aperçu ne doit jamais dépendre d'un rendu
 * à la volée (Satori + sharp, ~1 s) ni d'une API. Cette route n'est que l'outil de
 * fabrication.
 *
 * Régénérer après toute retouche — sous un NOUVEAU nom, jamais en écrasant l'ancien : le
 * fichier est servi avec un mois de cache et les aperçus des messageries gardent leur
 * copie par URL. Mettre à jour `OG_IMAGE` dans `src/lib/seo.ts` et la liste de
 * `next.config.mjs` :
 *   npm run dev
 *   curl -s http://localhost:3001/visuels/og > public/og-image-v3.jpg
 *
 * ─────────────────────────── CE QUI EST INTERDIT ICI ───────────────────────────────────
 *
 * Aucun chiffre de gain ni de rentabilité : le ROI mesuré est négatif, la vignette vend
 * la qualité de l'analyse, jamais un gain. Et la mention légale (18+, jeu à risque) reste
 * sur l'image : une communication commerciale hippique la porte, y compris quand elle
 * voyage seule dans une bulle de conversation.
 */

// Pas de prérendu au build : cette route est un OUTIL, appelée à la main quand on
// retouche la vignette. La faire fabriquer une image à chaque `next build` coûterait du
// temps de build pour un fichier qui, lui, est commité.
export const dynamic = "force-dynamic";

const L = 1200;
const H = 630;
/** Le panneau clair porte le logo, qui est dessiné sur blanc — on ne le détoure pas. */
const PANNEAU_L = 520;

const OR = "#E0A63C";
const OR_PROFOND = "#B45309";
const ENCRE = "#111827";
const ENCRE_HAUT = "#1B2331";
/** Le logo est livré sur un carré BLANC opaque, pas détouré : le panneau doit être blanc
 *  lui aussi, sinon le fichier dessine son propre cadre au milieu de la vignette. */
const BLANC = "#FFFFFF";
const TEXTE_DOUX = "#A7B0BE";
const TEXTE_TENU = "#71798A";

async function polices() {
  const dossier = path.join(process.cwd(), "src", "assets", "fonts");
  const lire = (f: string) => fs.readFile(path.join(dossier, f));
  const [groteskBold, groteskMedium, interRegular, interSemi] = await Promise.all([
    lire("SpaceGrotesk-Bold.ttf"),
    lire("SpaceGrotesk-Medium.ttf"),
    lire("Inter-Regular.ttf"),
    lire("Inter-SemiBold.ttf"),
  ]);
  return [
    { name: "Grotesk", data: groteskBold, weight: 700 as const, style: "normal" as const },
    { name: "Grotesk", data: groteskMedium, weight: 500 as const, style: "normal" as const },
    { name: "Inter", data: interRegular, weight: 400 as const, style: "normal" as const },
    { name: "Inter", data: interSemi, weight: 600 as const, style: "normal" as const },
  ];
}

export async function GET() {
  // Le VRAI logo, en haute définition et rogné de sa marge blanche : `public/logo.png`
  // ne fait que 160 × 87, le médaillon y baverait à cette taille.
  const logo = await imageEnDataUri("logo-blackturf.png", { largeur: 760, rogner: true });

  const rendu = new ImageResponse(
    (
      <div style={{ display: "flex", width: L, height: H, backgroundColor: ENCRE }}>
        {/* Panneau clair : le logo, seul, sur son fond d'origine. */}
        <div
          style={{
            display: "flex",
            width: PANNEAU_L,
            height: H,
            backgroundColor: BLANC,
            alignItems: "center",
            justifyContent: "center",
            borderRight: `6px solid ${OR}`,
          }}
        >
          {logo ? (
            <img src={logo} alt="BlackTurf" width={392} height={385} />
          ) : (
            <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 64, color: ENCRE }}>
              BlackTurf
            </span>
          )}
        </div>

        {/* Panneau sombre : la proposition, en trois niveaux de lecture. */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            width: L - PANNEAU_L,
            height: H,
            backgroundColor: ENCRE,
            padding: "62px 64px 48px 60px",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span
              style={{
                fontFamily: "Inter",
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: 3.6,
                color: OR,
              }}
            >
              PRONOSTICS PMU PAR IA
            </span>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 52,
                lineHeight: 1.14,
                letterSpacing: -1.4,
                color: "#FFFFFF",
                marginTop: 26,
              }}
            >
              Une probabilité par cheval, un plan de mise sur votre budget.
            </span>
            <div style={{ display: "flex", width: 96, height: 4, backgroundColor: OR, marginTop: 30 }} />
            <span
              style={{
                fontFamily: "Inter",
                fontSize: 25,
                lineHeight: 1.44,
                color: TEXTE_DOUX,
                marginTop: 26,
              }}
            >
              Notés aux rapports réels du PMU. Modèle réentraîné après chaque course.
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", width: "100%", height: 1, backgroundColor: ENCRE_HAUT }} />
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                justifyContent: "space-between",
                marginTop: 22,
              }}
            >
              <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 30, color: "#FFFFFF" }}>
                blackturf.fr
              </span>
              <span style={{ fontFamily: "Inter", fontSize: 17, color: TEXTE_TENU }}>
                18+ · jouer comporte des risques
              </span>
            </div>
          </div>
        </div>
      </div>
    ),
    { width: L, height: H, fonts: await polices() },
  );

  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    // JPEG : c'est le format le mieux avalé par les aperçus (Safari, iMessage, LinkedIn),
    // et 4:2:0 sur un aplat de texte reste net à cette qualité.
    const jpeg = await sharp(png).flatten({ background: OR_PROFOND }).jpeg({ quality: 92 }).toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=600" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
