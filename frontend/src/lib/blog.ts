import type { ComponentType } from "react";
import * as quinte from "@/content/blog/analyser-quinte-du-jour";
import * as cotes from "@/content/blog/comprendre-les-cotes";
import * as bankroll from "@/content/blog/gestion-bankroll-courses";
import * as ia from "@/content/blog/ia-pronostics-hippiques";
import * as trot from "@/content/blog/strategies-paris-trot";
import * as favori from "@/content/blog/favori-ou-outsider";
import * as flexi from "@/content/blog/quinte-flexi-strategie";
import * as tierce from "@/content/blog/tierce-ordre-ou-desordre";
import * as deuxSurQuatre from "@/content/blog/comprendre-le-2sur4";
import * as couple from "@/content/blog/couple-gagnant-ou-place";
import * as reduc from "@/content/blog/reduction-kilometrique-trot";
import * as champ from "@/content/blog/champ-reduit-base-tickets";
import * as chatgpt from "@/content/blog/chatgpt-pronostic-hippique";
import * as iaGratuit from "@/content/blog/pronostic-ia-gratuit";

export interface ArticleMeta {
  slug: string;
  title: string;
  description: string;
  date: string; // YYYY-MM-DD
  updated: string;
  tags: string[];
  readingMinutes: number;
}

export interface Article extends ArticleMeta {
  Body: ComponentType;
}

const MODULES = [
  quinte, cotes, bankroll, ia, trot, favori,
  flexi, tierce, deuxSurQuatre, couple, reduc, champ,
  chatgpt, iaGratuit,
];

// Trié du plus récent au plus ancien (date décroissante), puis par titre pour un ordre stable
// quand les dates sont égales.
export const ARTICLES: Article[] = MODULES.map((m) => ({
  ...(m.meta as ArticleMeta),
  Body: m.default as ComponentType,
})).sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title, "fr"));

export function getArticle(slug: string): Article | undefined {
  return ARTICLES.find((a) => a.slug === slug);
}

export function formatDateFr(iso: string): string {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "Europe/Paris",
    }).format(new Date(iso + "T12:00:00Z"));
  } catch {
    return iso;
  }
}
