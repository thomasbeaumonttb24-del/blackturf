import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong, jourCourt, periodeCourte } from "@/lib/seo";
import {
  PlanEnsemble, PLAN_L, PLAN_H, photoDuCycle, photoEnDataUri, imageEnDataUri,
  type DonneesMosaique, type SemaineMosaique,
} from "@/lib/mosaique";

/**
 * L'IMAGE ENTIÈRE, telle qu'elle apparaîtra sur la grille du profil au bout de six
 * dimanches. Sert à VALIDER avant de publier la première tuile.
 *
 * Elle n'existe que pour être regardée : une mosaïque ne se juge pas tuile par tuile,
 * elle se juge d'un bloc — et une fois les six publiées, plus rien ne se corrige.
 *
 * Ce que l'aperçu ne peut PAS montrer : les six tuiles porteront les chiffres de six
 * semaines DIFFÉRENTES, alors qu'ici elles portent toutes ceux de la même. La
 * composition, les raccords et la photo sont exacts ; seuls les nombres se répéteront
 * d'une case à l'autre.
 */
export const revalidate = 600;

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

// Le plan d'ensemble fait 3104 × 2700. On le sert réduit : c'est un aperçu qu'on
// regarde sur un écran, pas un fichier à publier.
const APERCU_L = 1200;

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
    pctTop1: null, nbPartants: 0, meilleur: null, autresPlans: [], meilleureJournee: null,
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
        // Le podium arrive déjà dédoublonné et trié par l'API ; on écarte seulement
        // le premier, qui est affiché en grand juste au-dessus.
        autresPlans: (Array.isArray(d.meilleurs_plans) ? d.meilleurs_plans : [])
          .slice(1, 3)
          .map((p: Record<string, unknown>) => ({
            hippodrome: String(p.hippodrome ?? ""),
            code: String(p.code ?? ""),
            mise: Number(p.mise ?? 0),
            retour: Number(p.retour ?? 0),
            typePari: p.type_pari ? String(p.type_pari) : null,
          })),
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
    // Un aperçu sans données reste lisible ; un aperçu qui plante, non.
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
    // Le fond reste NET : c'est ce qui permet de voir, d'une vignette à la suivante,
    // qu'un cheval ou une lice continue au-delà du bord — donc de reconnaître une
    // seule image. Assombri un peu, saturé un peu : la carte est blanche, il lui faut
    // un fond sombre, et les casaques colorées font les points de repère.
    photo: await photoEnDataUri(photoDuCycle(cycle), {
      largeur: PLAN_L, hauteur: PLAN_H, luminosite: 1.02, saturation: 1.16,
    }),
    // Le VRAI logo, rogné de sa marge blanche. `logo.png` du dossier public ne fait
    // que 160 × 87 : le médaillon y occupe 70 px et baverait. Celui-ci est la source
    // haute définition.
    horse: await imageEnDataUri("logo-blackturf.png", { largeur: 360, rogner: true }),
  };
}

export async function GET(req: Request) {
  const d = await donnees(new URL(req.url).searchParams.get("semaine"));

  const rendu = new ImageResponse(<PlanEnsemble d={d} />, {
    width: PLAN_L,
    height: PLAN_H,
    fonts: await polices(),
  });

  const png = Buffer.from(await rendu.arrayBuffer());
  try {
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(png)
      .flatten({ background: "#F5F2EA" })
      .resize(APERCU_L)
      .jpeg({ quality: 88 })
      .toBuffer();
    return new Response(new Uint8Array(jpeg), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=600" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=60" },
    });
  }
}
