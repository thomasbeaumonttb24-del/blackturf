import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import {
  jourParis,
  jourLong,
  jourCourtAnnee,
  ogBase,
  twitterBase,
  PREMIER_JOUR_ARCHIVE,
} from "@/lib/seo";
import { ResultatsJour } from "@/components/seo/ResultatsJour";

/**
 * 10 minutes, et non une heure comme auparavant.
 *
 * Cette page connaît un cas particulier : la journée EN COURS est redirigée vers
 * `/resultats`. Cette redirection entre elle aussi dans le cache de route ; le lendemain,
 * la même URL doit au contraire servir l'archive. Le délai de bascule est donc borné par
 * `revalidate` — dix minutes après minuit plutôt qu'une heure, au moment où personne ne
 * consulte l'archive de la veille.
 */
export const revalidate = 600;

/**
 * Vide, pour la même raison que sur la fiche course : sans `generateStaticParams`, Next
 * ne met pas le HTML en cache et sert la page en `no-store`. Aucune journée n'est
 * pré-générée au build — elles vieilliraient dès le lendemain — chacune est rendue à sa
 * première demande puis mise en cache.
 */
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ jour: string }> };

/** Accepte AAAA-MM-JJ, et uniquement des journées réellement couvertes par le site. */
function jourValide(jour: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(jour)) return false;
  const d = new Date(`${jour}T12:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== jour) return false;
  // Rien avant la mise en service, rien dans le futur : sans cette borne, un robot peut
  // fabriquer une infinité d'URLs de dates vides (piège à exploration classique).
  // La borne était fixée au 1er janvier 2026 alors que la base remonte au 1er septembre
  // 2025 : quatre mois d'arrivées réelles répondaient 404 (vérifié le 2026-08-26 —
  // le 2025-10-01 porte 54 courses, toutes terminées, avec leurs rapports).
  return jour >= PREMIER_JOUR_ARCHIVE && jour <= jourParis();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { jour } = await params;
  if (!jourValide(jour)) return { title: "Résultats PMU" };
  // L'année figure dans le titre : sans elle, le 20 août 2026 et le 20 août 2027
  // portaient le même `<title>`, et Google n'en garde qu'un.
  const title = `Résultats PMU du ${jourCourtAnnee(jour)} — arrivées et rapports`;
  const description = `Arrivées officielles et rapports PMU du ${jourLong(
    jour,
  )} : Quinté+, Quarté+, Tiercé, Couplé, Simple et 2 sur 4.`;
  return {
    title,
    description,
    alternates: { canonical: `/resultats/${jour}` },
    openGraph: ogBase({ title, description, url: `/resultats/${jour}`, type: "article" }),
    twitter: twitterBase({ title, description }),
  };
}

export default async function ResultatsArchivePage({ params }: Props) {
  const { jour } = await params;
  if (!jourValide(jour)) notFound();
  // La journée en cours a son URL propre : deux adresses pour le même contenu se
  // seraient concurrencées dans l'index.
  if (jour === jourParis()) redirect("/resultats");
  return <ResultatsJour jour={jour} />;
}
