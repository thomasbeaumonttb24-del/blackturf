import type { Metadata } from "next";
import { jourParis, jourLong, jourCourt } from "@/lib/seo";
import { ResultatsJour } from "@/components/seo/ResultatsJour";

export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  const title = `Résultats PMU du ${jourCourt(jour)} — arrivées et rapports`;
  const description = `Toutes les arrivées officielles et les rapports PMU du ${jourLong(
    jour,
  )} : Quinté+, Quarté+, Tiercé, Couplé, Simple et 2 sur 4, course par course et réunion par réunion.`;
  return {
    title,
    description,
    alternates: { canonical: "/resultats" },
    openGraph: { title: `${title} | BlackTurf`, description, url: "https://blackturf.fr/resultats" },
  };
}

export default async function ResultatsDuJourPage() {
  return <ResultatsJour jour={jourParis()} />;
}
