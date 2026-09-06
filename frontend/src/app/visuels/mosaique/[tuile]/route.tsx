import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong, jourCourt, periodeCourte } from "@/lib/seo";
import {
  Tuile, TUILE_L, TUILE_H, PLAN_L, PLAN_H, photoDuCycle, photoEnDataUri, imageEnDataUri,
  type DonneesMosaique, type SemaineMosaique,
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

async function donnees(semaine: string | null): Promise<DonneesMosaique> {
  const vide: SemaineMosaique = {
    periode: "", numero: 1, position: 0, nbCourses: 0, nbHippodromes: 0, nbPlans: 0, nbPlansGagnants: 0,
    totalRetour: 0, pctTop3: null, nbTop3: 0, nbAnalysees: 0, hasardTop3: null,
    pctTop1: null, nbPartants: 0, meilleur: null, meilleureJournee: null,
  };
  let s = vide;
  let cycle = 0;
  try {
    const url = new URL(`${API}/stats/bilan-semaine`);
    if (semaine) url.searchParams.set("fin", semaine);
    const res = await fetch(url.toString(), { next: { revalidate: 600 } });
    if (res.ok) {
      const d = await res.json();
      const a = d.analyse ?? {};
      const m = d.meilleur_plan;
      const mj = d.meilleure_journee;
      const nombre = (v: unknown) => (v === null || v === undefined ? null : Number(v));
      cycle = Number(d.cycle ?? 0);
      s = {
        periode: periodeCourte(String(d.debut), String(d.fin)),
        numero: Number(d.semaine_index ?? 0) + 1,
        position: Number(d.rang_dans_le_cycle ?? 1) - 1,
        nbCourses: Number(d.nb_courses ?? 0),
        nbHippodromes: Number(d.nb_hippodromes ?? 0),
        nbPlans: Number(d.nb_plans ?? 0),
        nbPlansGagnants: Number(d.nb_plans_gagnants ?? 0),
        totalRetour: Number(d.total_retour ?? 0),
        pctTop3: nombre(a.pct_top3),
        nbTop3: Number(a.nb_top3 ?? 0),
        nbAnalysees: Number(a.nb_courses_analysees ?? 0),
        hasardTop3: nombre(a.hasard_top3),
        pctTop1: nombre(a.pct_top1),
        nbPartants: Number(a.nb_partants ?? 0),
        meilleur: m
          ? {
              hippodrome: String(m.hippodrome ?? ""),
              code: String(m.code ?? ""),
              mise: Number(m.mise ?? 0),
              retour: Number(m.retour ?? 0),
              net: Number(m.net ?? 0),
              typePari: m.type_pari ? String(m.type_pari) : null,
            }
          : null,
        meilleureJournee: mj
          ? {
              jourLong: jourCourt(String(mj.jour)),
              nbCourses: Number(mj.nb_courses ?? 0),
              nbTop3: Number(mj.nb_top3 ?? 0),
              pctTop3: Number(mj.pct_top3 ?? 0),
            }
          : null,
      };
    }
  } catch {
    // Un visuel sans données reste publiable ; un visuel qui plante, non.
  }
  const jour = jourParis();
  return {
    jourLong: jourLong(jour),
    jourCourt: jourCourt(jour),
    semaine: s,
    nbCourses: s.nbCourses,
    nbPlans: s.nbPlans,
    nbReunions: s.nbHippodromes,
    plans: [],
    // LA PHOTO SUIT LE CYCLE, PAS LA DATE : les six tuiles sont publiées à six
    // dimanches d'écart et doivent montrer la MÊME image, sinon les raccords ne
    // tombent pas. Elle couvre TOUT le plan (3104 × 2700), pas une bande.
    // Le fond reste NET : c'est ce qui permet de voir, d'une vignette à la suivante,
    // qu'un cheval ou une lice continue au-delà du bord — donc de reconnaître une
    // seule image. Assombri un peu, saturé un peu : la carte est blanche, il lui faut
    // un fond sombre, et les casaques colorées font les points de repère.
    photo: await photoEnDataUri(photoDuCycle(cycle), {
      largeur: PLAN_L, hauteur: PLAN_H, luminosite: 0.92, saturation: 1.14,
    }),
    // Le VRAI logo, rogné de sa marge blanche. `logo.png` du dossier public ne fait
    // que 160 × 87 : le médaillon y occupe 70 px et baverait. Celui-ci est la source
    // haute définition.
    horse: await imageEnDataUri("logo-blackturf.png", { largeur: 360, rogner: true }),
  };
}

/** `tuile` s'écrit « r-c » : 0-0 en haut à gauche, 1-2 en bas à droite. */
export async function GET(req: Request, ctx: { params: Promise<{ tuile: string }> }) {
  const { tuile } = await ctx.params;
  const m = /^([01])-([012])$/.exec(tuile.replace(/\.jpg$/, ""));
  if (!m) return new Response("Tuile inconnue", { status: 404 });

  const rangee = Number(m[1]);
  const colonne = Number(m[2]);
  // `?semaine=AAAA-MM-JJ` (un samedi) : la publication du dimanche porte sur la
  // semaine ÉCOULÉE, et une tuile doit rester rendable après coup — sans quoi le
  // visuel publié devient irrécupérable dès le dimanche suivant.
  const d = await donnees(new URL(req.url).searchParams.get("semaine"));

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
