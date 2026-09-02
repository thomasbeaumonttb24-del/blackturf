import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { photoEnDataUri, TUILE_L, TUILE_H } from "@/lib/mosaique";
import { TuileSite, type DonneesSite } from "@/lib/mosaique-site";

// Ces chiffres bougent de quelques unités par jour : une heure de cache suffit largement
// et évite de recomposer un plan de 3104 × 2700 à chaque appel.
export const revalidate = 3600;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/**
 * Photo FIXE, contrairement à la mosaïque du jour qui en fait tourner cinq.
 *
 * Celle-ci est la vitrine : elle est publiée une fois et reste en haut du profil. Une
 * photo qui changerait selon le quantième rendrait deux rendus de la même mosaïque
 * différents, et donc impossible de republier une tuile à l'identique si Instagram en
 * refusait une en cours de série.
 */
const PHOTO = "hero-1600.webp";

/**
 * Les polices sont EMBARQUÉES, pas référencées : Satori n'a pas de navigateur derrière
 * lui et retomberait sur une fonte générique, écrasant toute la direction typographique.
 */
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

/**
 * Les chiffres de fond du service.
 *
 * En cas d'API indisponible on renvoie des zéros — et la tuile qui les porte affiche
 * alors « 0 courses réglées », ce qui est visible immédiatement à la relecture. C'est
 * volontaire : mieux vaut un visuel manifestement faux qu'un visuel plausible fabriqué à
 * partir de valeurs de repli écrites en dur, qu'on publierait sans s'en apercevoir.
 */
async function donnees(): Promise<DonneesSite> {
  let coursesEnBase = 0;
  let partantsAnalyses = 0;
  let coursesReglees = 0;
  let journeesPubliees = 0;
  try {
    const res = await fetch(`${API}/stats/chiffres-site`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const d = await res.json();
      coursesEnBase = Number(d.courses_en_base ?? 0);
      partantsAnalyses = Number(d.partants_analyses ?? 0);
      coursesReglees = Number(d.courses_reglees ?? 0);
      journeesPubliees = Number(d.journees_publiees ?? 0);
    }
  } catch {
    // Un visuel sans données reste rendu ; un visuel qui plante, non.
  }
  return {
    coursesEnBase,
    partantsAnalyses,
    coursesReglees,
    journeesPubliees,
    photo: await photoEnDataUri(PHOTO),
  };
}

/** `tuile` s'écrit « r-c » : 0-0 en haut à gauche, 1-2 en bas à droite. */
export async function GET(_req: Request, ctx: { params: Promise<{ tuile: string }> }) {
  const { tuile } = await ctx.params;
  const m = /^([01])-([012])$/.exec(tuile.replace(/\.jpg$/, ""));
  if (!m) return new Response("Tuile inconnue", { status: 404 });

  const rangee = Number(m[1]);
  const colonne = Number(m[2]);
  const d = await donnees();

  const rendu = new ImageResponse(<TuileSite d={d} rangee={rangee} colonne={colonne} />, {
    width: TUILE_L,
    height: TUILE_H,
    fonts: await polices(),
  });

  // L'API de publication Instagram n'accepte que du JPEG.
  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(png).flatten({ background: "#F5F2EA" }).jpeg({ quality: 92 }).toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=3600" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
