import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { jourParis, jourLong, jourCourt } from "@/lib/seo";
import { ResultatsJour } from "@/components/seo/ResultatsJour";

export const revalidate = 3600; // une journée passée ne bouge plus : cache long

type Props = { params: Promise<{ jour: string }> };

/** Accepte AAAA-MM-JJ, et uniquement des journées réellement couvertes par le site. */
function jourValide(jour: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(jour)) return false;
  const d = new Date(`${jour}T12:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== jour) return false;
  // Rien avant la mise en service, rien dans le futur : sans cette borne, un robot peut
  // fabriquer une infinité d'URLs de dates vides (piège à exploration classique).
  return jour >= "2026-01-01" && jour <= jourParis();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { jour } = await params;
  if (!jourValide(jour)) return { title: "Résultats PMU" };
  const title = `Résultats PMU du ${jourCourt(jour)} — arrivées et rapports`;
  const description = `Les arrivées officielles et les rapports PMU du ${jourLong(
    jour,
  )} : Quinté+, Quarté+, Tiercé, Couplé, Simple et 2 sur 4, réunion par réunion.`;
  return {
    title,
    description,
    alternates: { canonical: `/resultats/${jour}` },
    openGraph: {
      title: `${title} | BlackTurf`,
      description,
      url: `https://blackturf.fr/resultats/${jour}`,
      type: "article",
    },
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
