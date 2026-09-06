import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong } from "@/lib/seo";
import { jourDemande } from "@/lib/visuels";
import { photoDuJour, photoEnDataUri, imageEnDataUri } from "@/lib/mosaique";
import {
  Story, STORY_L, STORY_H, PHOTO_H, type DonneesStory, type MeilleurPlan,
} from "@/lib/story";

// Les règlements du jour bougent encore pendant l'après-midi (un rapport Multi publié
// en différé ajoute un plan gagnant) : dix minutes de cache, pas un quart d'heure.
export const revalidate = 600;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

const PHOTO_L = STORY_L;

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

async function donneesStory(jour: string): Promise<DonneesStory> {
  let pctTop3: number | null = null;
  let pctTop1: number | null = null;
  let hasardTop3: number | null = null;
  let nbTop3 = 0;
  let nbTop1 = 0;
  let nbAnalysees = 0;
  let nbPartants = 0;
  let nbHippodromes = 0;
  let nbPlans = 0;
  let nbPlansGagnants = 0;
  let totalRetour = 0;
  let meilleur: MeilleurPlan | null = null;
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour?jour=${jour}`, {
      next: { revalidate: 600 },
    });
    if (res.ok) {
      const d = await res.json();
      const p = (d.plans ?? [])[0];
      if (p) {
        meilleur = {
          hippodrome: String(p.hippodrome ?? ""),
          code: String(p.code ?? ""),
          mise: Number(p.mise ?? 0),
          retour: Number(p.retour ?? 0),
          net: Number(p.net ?? 0),
          typePari: p.type_pari ? String(p.type_pari) : null,
        };
      }
      nbHippodromes = Number(d.nb_hippodromes ?? 0);
      nbPlans = Number(d.nb_plans ?? 0);
      nbPlansGagnants = Number(d.nb_plans_gagnants ?? 0);
      totalRetour = Number(d.total_retour ?? 0);
      const a = d.analyse ?? {};
      nbAnalysees = Number(a.nb_courses_analysees ?? 0);
      nbTop3 = Number(a.nb_top3 ?? 0);
      nbTop1 = Number(a.nb_top1 ?? 0);
      nbPartants = Number(a.nb_partants ?? 0);
      // `null` reste `null` : une journée pas encore analysée doit se TAIRE, pas
      // afficher 0 % — un « 0 % » se lit comme un échec, pas comme une absence.
      pctTop3 = a.pct_top3 === null || a.pct_top3 === undefined ? null : Number(a.pct_top3);
      pctTop1 = a.pct_top1 === null || a.pct_top1 === undefined ? null : Number(a.pct_top1);
      hasardTop3 =
        a.hasard_top3 === null || a.hasard_top3 === undefined ? null : Number(a.hasard_top3);
    }
  } catch {
    // Un visuel sans données reste publiable ; un visuel qui plante, non.
  }
  const [photo, horse] = await Promise.all([
    photoEnDataUri(photoDuJour(jour), {
      largeur: PHOTO_L, hauteur: PHOTO_H, luminosite: 1.04,
      // 0,82 : la fenêtre part du bas, on ne perd que du ciel. La détection de sujet
      // de `sharp` centrait le cheval et lui coupait les jambes.
      ancrage: 0.82,
    }),
    imageEnDataUri("logo-horse.png", { largeur: 200 }),
  ]);
  return {
    jourLong: jourLong(jour),
    pctTop3,
    nbTop3,
    nbAnalysees,
    hasardTop3,
    pctTop1,
    nbTop1,
    nbPartants,
    nbHippodromes,
    meilleur,
    totalRetour,
    nbPlans,
    nbPlansGagnants,
    photo,
    horse,
  };
}

export async function GET(req: Request) {
  // `?jour=AAAA-MM-JJ` : la story de bilan se publie le lendemain matin, quand la
  // journée est enfin réglée. Sans ce paramètre, le visuel de la veille disparaît au
  // premier passage de minuit — constaté sur le 2026-09-05, plus récupérable au réveil.
  const jour = jourDemande(req.url, jourParis());
  const d = await donneesStory(jour);

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
