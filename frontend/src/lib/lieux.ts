import { titleCase } from "@/lib/seo";
import { getHippodrome, nomCourt, nomLieu, slugHippodrome } from "@/lib/hippodromes";

/** « Le Mans » → « au Mans », « Les Sables » → « aux Sables », « Vincennes » → « à Vincennes ». */
export function aLieu(nom: string): string {
  if (/^le /i.test(nom)) return `au ${nom.slice(3)}`;
  if (/^les /i.test(nom)) return `aux ${nom.slice(4)}`;
  if (/^la /i.test(nom)) return `à la ${nom.slice(3)}`;
  return `à ${nom}`;
}

/** « Le Bouscat » → « du Bouscat », « Auteuil » → « d'Auteuil », « Caen » → « de Caen ». */
export function deLieu(nom: string): string {
  if (/^le /i.test(nom)) return `du ${nom.slice(3)}`;
  if (/^les /i.test(nom)) return `des ${nom.slice(4)}`;
  if (/^la /i.test(nom)) return `de la ${nom.slice(3)}`;
  return /^[aeiouyéèêàâîôû]/i.test(nom) ? `d'${nom}` : `de ${nom}`;
}

/**
 * Nom d'un hippodrome tel que le PMU l'écrit (« PARISLONGCHAMP », « LE LION D'ANGERS »),
 * rendu lisible. Quand le lieu a une fiche, son nom soigné fait foi (accents, traits
 * d'union, « ParisLongchamp ») ; sinon, mise en casse simple.
 */
export function lieuCourse(label: string | null | undefined): { nom: string; a: string; de: string } {
  const slug = slugHippodrome(label ?? "");
  const h = slug ? getHippodrome(slug) : undefined;
  if (h) {
    const avecArticle = nomCourt(h); // « de Vincennes », « du Croisé-Laroche », « d'Auteuil »
    const a = avecArticle
      .replace(/^de la /i, "à la ")
      .replace(/^des /i, "aux ")
      .replace(/^du /i, "au ")
      .replace(/^d'/i, "à ")
      .replace(/^de /i, "à ");
    // « du Lion-d'Angers » → « Le Lion-d'Angers » : l'article fait partie du nom.
    const nom = avecArticle.startsWith("du ")
      ? `Le ${avecArticle.slice(3)}`
      : avecArticle.startsWith("des ")
        ? `Les ${avecArticle.slice(4)}`
        : nomLieu(h);
    return { nom, a, de: avecArticle };
  }
  const nom = titleCase(label ?? "");
  return { nom, a: aLieu(nom), de: deLieu(nom) };
}
