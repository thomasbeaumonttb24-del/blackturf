import type { Metadata } from "next";
import {
  fetchQuinte,
  jourParis,
  jourLong,
  jourCourt,
  heureParis,
  ogBase,
  twitterBase,
} from "@/lib/seo";
import { lieuCourse } from "@/lib/lieux";
import { QuintePronostic } from "@/components/seo/QuintePronostic";

export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  const c = await fetchQuinte(jour);

  // « Pronostic Quinté » en tête : c'est la requête tapée (« pronostic quinté du jour »),
  // et Google pèse davantage les premiers mots du titre.
  const lieu = c ? lieuCourse(c.hippodrome_nom) : null;
  const title = lieu
    ? `Pronostic Quinté+ du ${jourCourt(jour)} ${lieu.a}`
    : `Pronostic Quinté+ du ${jourCourt(jour)} — IA, partants et arrivée`;
  // Extrait tronqué par Google vers 155-160 caractères : date, lieu et heure d'abord.
  const description = c
    ? `Pronostic du Quinté+ du ${jourLong(jour)} ${lieu?.a} : ${
        c.nb_partants
      } partants, départ à ${heureParis(c.date_heure)}. Classement IA, probabilité par cheval, arrivée et rapports.`
    : `Le pronostic du Quinté+ du ${jourLong(jour)} par l'IA : partants, probabilité par cheval, puis l'arrivée officielle et les rapports PMU.`;

  return {
    title,
    description,
    alternates: { canonical: "/quinte-du-jour" },
    openGraph: ogBase({ title, description, url: "/quinte-du-jour" }),
    twitter: twitterBase({ title, description }),
  };
}

export default async function QuinteDuJourPage() {
  return <QuintePronostic jour={jourParis()} />;
}
