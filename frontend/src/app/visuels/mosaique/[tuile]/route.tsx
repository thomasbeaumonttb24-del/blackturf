import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong, jourCourt } from "@/lib/seo";
import { jourDemande } from "@/lib/visuels";
import {
  Tuile, TUILE_L, TUILE_H, photoDuJour, photoEnDataUri,
  type DonneesMosaique, type PlanJour,
} from "@/lib/mosaique";

// Les données du jour ne bougent plus une fois les courses courues ; un quart d'heure de
// cache suffit et évite de recomposer un plan de 3104 × 2700 à chaque appel.
export const revalidate = 900;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/**
 * Les polices sont EMBARQUÉES, pas référencées.
 *
 * Satori n'a pas de navigateur derrière lui : sans fichier de police fourni, il retombe
 * sur une fonte générique qui écrase toute la direction typographique. Les quatre
 * fichiers vivent donc dans le dépôt, et sont lus au rendu.
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

async function donnees(jour: string): Promise<DonneesMosaique> {
  let plans: PlanJour[] = [];
  let nbCourses = 0;
  let nbReunions = 0;
  let nbPlans = 0;
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour?jour=${jour}`, {
      next: { revalidate: 600 },
    });
    if (res.ok) {
      const d = await res.json();
      plans = (d.plans ?? []).map((p: Record<string, unknown>) => ({
        hippodrome: String(p.hippodrome ?? ""),
        code: String(p.code ?? ""),
        mise: Number(p.mise ?? 0),
        retour: Number(p.retour ?? 0),
      }));
      nbCourses = Number(d.nb_courses ?? 0);
      nbReunions = Number(d.nb_reunions ?? 0);
      nbPlans = Number(d.nb_plans ?? 0);
    }
  } catch {
    // Un visuel sans données reste publiable ; un visuel qui plante, non.
  }
  return {
    jourLong: jourLong(jour),
    jourCourt: jourCourt(jour),
    nbCourses,
    nbReunions,
    nbPlans,
    plans,
    photo: await photoEnDataUri(photoDuJour(jour)),
  };
}

/** `tuile` s'écrit « r-c » : 0-0 en haut à gauche, 1-2 en bas à droite. */
export async function GET(req: Request, ctx: { params: Promise<{ tuile: string }> }) {
  const { tuile } = await ctx.params;
  const m = /^([01])-([012])$/.exec(tuile.replace(/\.jpg$/, ""));
  if (!m) return new Response("Tuile inconnue", { status: 404 });

  const rangee = Number(m[1]);
  const colonne = Number(m[2]);
  // `?jour=` : la mosaïque se publie le LENDEMAIN matin — c'est écrit dans la
  // docstring de l'endpoint depuis le 2026-08-23, mais aucun consommateur ne passait
  // le paramètre, et les six tuiles rendaient donc toujours le jour courant.
  const d = await donnees(jourDemande(req.url, jourParis()));

  const rendu = new ImageResponse(<Tuile d={d} rangee={rangee} colonne={colonne} />, {
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
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=900" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
