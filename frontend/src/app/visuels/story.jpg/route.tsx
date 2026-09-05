import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong } from "@/lib/seo";
import { photoDuJour, photoEnDataUri } from "@/lib/mosaique";
import { Story, STORY_L, STORY_H, PHOTO_H, type DonneesStory, type PlanStory } from "@/lib/story";

// Les règlements du jour bougent encore pendant l'après-midi (un rapport Multi publié en
// différé ajoute un plan gagnant) : dix minutes de cache, pas un quart d'heure.
export const revalidate = 600;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/**
 * Polices EMBARQUÉES : Satori n'a pas de navigateur derrière lui et retomberait sur une
 * fonte générique, ce qui écraserait toute la direction typographique.
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

async function donneesStory(): Promise<DonneesStory> {
  const jour = jourParis();
  let plans: PlanStory[] = [];
  let nbPlans = 0;
  let nbPlansGagnants = 0;
  let totalRetour = 0;
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour`, { next: { revalidate: 600 } });
    if (res.ok) {
      const d = await res.json();
      plans = (d.plans ?? []).map((p: Record<string, unknown>) => ({
        hippodrome: String(p.hippodrome ?? ""),
        code: String(p.code ?? ""),
        retour: Number(p.retour ?? 0),
      }));
      nbPlans = Number(d.nb_plans ?? 0);
      nbPlansGagnants = Number(d.nb_plans_gagnants ?? 0);
      totalRetour = Number(d.total_retour ?? 0);
    }
  } catch {
    // Un visuel sans données reste publiable ; un visuel qui plante, non.
  }
  return {
    jourLong: jourLong(jour),
    nbPlans,
    nbPlansGagnants,
    totalRetour,
    plans,
    photo: await photoEnDataUri(photoDuJour(jour), { largeur: STORY_L, hauteur: PHOTO_H, luminosite: 1.06 }),
  };
}

export async function GET() {
  const d = await donneesStory();

  const rendu = new ImageResponse(<Story d={d} />, {
    width: STORY_L,
    height: STORY_H,
    fonts: await polices(),
  });

  // L'API de publication Instagram n'accepte que du JPEG.
  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(png).flatten({ background: "#F5F2EA" }).jpeg({ quality: 92 }).toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=600" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
