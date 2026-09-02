import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { photoEnDataUri } from "@/lib/mosaique";
import { PlanReel, REEL_L, REEL_H, NB_PLANS, type DonneesReel } from "@/lib/reel";

export const revalidate = 3600;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/** Photo fixe : deux rendus du même Reel doivent être identiques au pixel près. */
const PHOTO = "duel.webp";

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

const taux = (v: unknown): number | null =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v);

async function donnees(n: number): Promise<DonneesReel> {
  let precisionTop3: number | null = null;
  let hasardTop3: number | null = null;
  let coursesMesurees = 0;
  try {
    const res = await fetch(`${API}/stats/chiffres-site`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const d = await res.json();
      precisionTop3 = taux(d.precision_top3);
      hasardTop3 = taux(d.hasard_top3);
      coursesMesurees = Number(d.courses_mesurees ?? 0);
    }
  } catch {
    // Un plan sans chiffres se rend quand même : il affiche « — », visible à la relecture.
  }
  // Seul le premier plan porte une photo : la charger pour les cinq autres coûterait
  // cinq conversions `sharp` pour rien.
  return {
    precisionTop3,
    hasardTop3,
    coursesMesurees,
    photo: n === 0 ? await photoEnDataUri(PHOTO) : null,
  };
}

/**
 * Un plan du Reel, en JPEG 1080 × 1920.
 *
 * L'assemblage en vidéo se fait AILLEURS : Satori ne produit que des images, et le
 * conteneur qui sert le site n'a pas à embarquer un encodeur vidéo.
 */
export async function GET(_req: Request, ctx: { params: Promise<{ plan: string }> }) {
  const { plan } = await ctx.params;
  const n = Number(plan.replace(/\.jpg$/, ""));
  if (!Number.isInteger(n) || n < 0 || n >= NB_PLANS) {
    return new Response(`Plan inconnu : attendu 0 à ${NB_PLANS - 1}`, { status: 404 });
  }

  const d = await donnees(n);
  const rendu = new ImageResponse(<PlanReel n={n} d={d} />, {
    width: REEL_L,
    height: REEL_H,
    fonts: await polices(),
  });

  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(png).flatten({ background: "#15181D" }).jpeg({ quality: 92 }).toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=3600" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
