import type { Metadata } from "next";
import {
  fetchQuinte,
  jourParis,
  decalerJours,
  jourLong,
  jourCourt,
  heureParis,
  titleCase,
  ogBase,
  twitterBase,
} from "@/lib/seo";
import { QuintePronostic } from "@/components/seo/QuintePronostic";

export const revalidate = 300;

/** « pronostic quinté demain » : la recherche se fait la veille au soir, quand le PMU
 *  vient de désigner la course support. L'URL est fixe ; le contenu suit le calendrier. */
export async function generateMetadata(): Promise<Metadata> {
  const jour = decalerJours(jourParis(), 1);
  const c = await fetchQuinte(jour);
  const title = c
    ? `Pronostic Quinté+ de demain (${jourCourt(jour)}) à ${titleCase(c.hippodrome_nom)} — IA`
    : `Pronostic Quinté+ de demain (${jourCourt(jour)}) — partants et analyse IA`;
  const description = c
    ? `Pronostic du Quinté+ de demain, ${jourLong(jour)}, à ${titleCase(c.hippodrome_nom)} : ${
        c.nb_partants
      } partants, départ à ${heureParis(c.date_heure)}. Classement IA, probabilité par cheval et cotes.`
    : `Le pronostic du Quinté+ de demain, ${jourLong(jour)} : course support, partants et analyse de l'IA dès que le PMU les publie, la veille au soir.`;
  return {
    title,
    description,
    alternates: { canonical: "/quinte-de-demain" },
    openGraph: ogBase({ title, description, url: "/quinte-de-demain" }),
    twitter: twitterBase({ title, description }),
  };
}

export default async function QuinteDeDemainPage() {
  return <QuintePronostic jour={decalerJours(jourParis(), 1)} demain />;
}
