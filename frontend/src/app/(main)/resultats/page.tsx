import type { Metadata } from "next";
import { jourParis, jourLong, jourCourt, ogBase, twitterBase, fetchQuinte, titleCase } from "@/lib/seo";
import { ResultatsJour } from "@/components/seo/ResultatsJour";

export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  // Pas d'année ici : cette URL désigne toujours « aujourd'hui », son titre est
  // remplacé chaque matin et n'entre jamais en concurrence avec lui-même.
  // Le Quinté+ nommé dans le titre : « arrivée quinté 12 octobre » est la requête
  // la plus tapée sur une journée de résultats.
  const quinte = await fetchQuinte(jour);
  const title = quinte
    ? `Résultats PMU du ${jourCourt(jour)} — arrivée du Quinté+ à ${titleCase(quinte.hippodrome_nom)}`
    : `Résultats PMU du ${jourCourt(jour)} — arrivées et rapports`;
  const description = quinte
    ? `Arrivée du Quinté+ du ${jourLong(jour)} à ${titleCase(quinte.hippodrome_nom)}, toutes les arrivées officielles et les rapports PMU : Quarté+, Tiercé, Couplé, Simple.`
    : `Arrivées officielles et rapports PMU du ${jourLong(
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
