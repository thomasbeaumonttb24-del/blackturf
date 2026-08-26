import type { Metadata } from "next";
import { jourParis, jourLong, jourCourt, ogBase, twitterBase } from "@/lib/seo";
import { ResultatsJour } from "@/components/seo/ResultatsJour";

export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  // Pas d'année ici : cette URL désigne toujours « aujourd'hui », son titre est
  // remplacé chaque matin et n'entre jamais en concurrence avec lui-même.
  const title = `Résultats PMU du ${jourCourt(jour)} — arrivées et rapports`;
  const description = `Arrivées officielles et rapports PMU du ${jourLong(
    jour,
  )} : Quinté+, Quarté+, Tiercé, Couplé, Simple et 2 sur 4.`;
  return {
    title,
    description,
    alternates: { canonical: "/resultats" },
    openGraph: ogBase({ title, description, url: "/resultats" }),
    twitter: twitterBase({ title, description }),
  };
}

export default async function ResultatsDuJourPage() {
  return <ResultatsJour jour={jourParis()} />;
}
