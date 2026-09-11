import fs from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { jourParis, jourLong } from "@/lib/seo";
import { jourDemande } from "@/lib/visuels";
import { photoDuJour, photoEnDataUri, imageEnDataUri } from "@/lib/mosaique";
import {
  Story, STORY_L, STORY_H, PHOTO_H, type DonneesStory, type MeilleurPlan,
} from "@/lib/story";

// AUCUN CACHE, ni sur la route ni sur les données — incident du 2026-09-11.
//
// La story du 10/09 est partie à 02 h 30 avec « 0 € rendu », sans le taux de Top 3 ni
// le meilleur gain. L'API était juste (159 plans, 961,80 €) ; c'est le cache de données
// de Next (`fetch` + `next: { revalidate: 600 }`) qui a servi à Meta la réponse lue la
// VEILLE à 06 h 32, quand la journée n'avait encore aucun plan. Le cache périmé est
// servi D'ABORD (stale-while-revalidate) et rafraîchi ensuite : Meta a récupéré l'image
// à 02:30:08, le vrai appel à l'API est parti à 02:30:10. Un visuel qui ne se publie
// qu'une fois et ne se corrige plus n'a rien à gagner d'un cache.
export const dynamic = "force-dynamic";

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

/** Ce que l'API dit de la journée, lu sans cache. `null` = API injoignable ou en erreur. */
async function bilanDuJour(jour: string): Promise<Record<string, any> | null> {
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour?jour=${jour}`, {
      cache: "no-store",
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

async function donneesStory(jour: string, d: Record<string, any>): Promise<DonneesStory> {
  const p = (d.plans ?? [])[0];
  const meilleur: MeilleurPlan | null = p
    ? {
        hippodrome: String(p.hippodrome ?? ""),
        code: String(p.code ?? ""),
        mise: Number(p.mise ?? 0),
        retour: Number(p.retour ?? 0),
        net: Number(p.net ?? 0),
        typePari: p.type_pari ? String(p.type_pari) : null,
      }
    : null;
  const nbHippodromes = Number(d.nb_hippodromes ?? 0);
  const nbPlans = Number(d.nb_plans ?? 0);
  const nbPlansGagnants = Number(d.nb_plans_gagnants ?? 0);
  const totalRetour = Number(d.total_retour ?? 0);
  const a = d.analyse ?? {};
  const nbAnalysees = Number(a.nb_courses_analysees ?? 0);
  const nbTop3 = Number(a.nb_top3 ?? 0);
  const nbTop1 = Number(a.nb_top1 ?? 0);
  const nbPartants = Number(a.nb_partants ?? 0);
  // `null` reste `null` : une journée pas encore analysée doit se TAIRE, pas
  // afficher 0 % — un « 0 % » se lit comme un échec, pas comme une absence.
  const nombre = (v: unknown) => (v === null || v === undefined ? null : Number(v));
  const pctTop3 = nombre(a.pct_top3);
  const pctTop1 = nombre(a.pct_top1);
  const hasardTop3 = nombre(a.hasard_top3);
  // `photoDuJour` renvoie null quand le fonds est epuise : on rend alors la story
  // SANS bandeau photo plutot que de republier une image deja parue.
  const fichierPhoto = photoDuJour(jour);
  const [photo, horse] = await Promise.all([
    fichierPhoto === null ? Promise.resolve(null) : photoEnDataUri(fichierPhoto, {
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
  const bilan = await bilanDuJour(jour);

  // PAS D'IMAGE PLUTÔT QU'UNE IMAGE FAUSSE. Ce visuel est récupéré par Meta et publié
  // tel quel : s'il sort avec des zéros, c'est une story à zéro qui part, et elle ne se
  // corrige plus. Une erreur HTTP fait échouer la publication, que le job retente au
  // passage suivant — c'est le seul échec rattrapable des deux.
  if (!bilan) {
    return new Response("Bilan du jour indisponible", {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }

  // `?plans=N` : le nombre de plans que le job de publication a lu au moment de décider
  // que la journée était publiable. L'image doit porter CES chiffres-là ; si l'API en
  // dit autre chose, ce n'est pas la journée que le job a validée, on ne la rend pas.
  const attendu = new URL(req.url).searchParams.get("plans");
  if (attendu !== null) {
    const nbPlans = Number(bilan.nb_plans ?? 0);
    if (!bilan.journee_complete || String(nbPlans) !== attendu) {
      return new Response(
        `Bilan différent de celui validé (plans=${nbPlans}, attendu=${attendu}, ` +
          `journee_complete=${Boolean(bilan.journee_complete)})`,
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }
  }

  const d = await donneesStory(jour, bilan);

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
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "no-store" },
    });
  } catch {
    return new Response(new Uint8Array(png), {
      headers: { "Content-Type": "image/png", "Cache-Control": "no-store" },
    });
  }
}
