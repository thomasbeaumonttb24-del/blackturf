/**
 * Libellés publics des paris PMU et mise de référence de chaque rapport.
 *
 * Le PMU publie ses rapports pour une mise unitaire qui n'est PAS la même selon le pari
 * (1 € pour le Simple, 1 € pour le Couplé, 1 € pour le Tiercé/Quarté/Quinté en ligne…),
 * et les nomme avec le préfixe « e_ » de l'offre en ligne. Afficher « e_quinte_plus »
 * tel quel ne veut rien dire pour un visiteur — et encore moins pour un moteur de
 * recherche qui doit reconnaître « rapport du quinté ».
 */
export const LIBELLE_PARI: Record<string, string> = {
  e_simple_gagnant: "Simple Gagnant",
  e_simple_place: "Simple Placé",
  e_couple_gagnant: "Couplé Gagnant",
  e_couple_place: "Couplé Placé",
  e_couple_ordre: "Couplé Ordre",
  e_deux_sur_quatre: "2 sur 4",
  e_tierce: "Tiercé",
  e_quarte_plus: "Quarté+",
  e_quinte_plus: "Quinté+",
  e_multi: "Multi",
  e_pick5: "Pick 5",
  e_super_quatre: "Super 4",
  e_trio: "Trio",
  e_quinte_plus_international: "Quinté+ international",
  e_tierce_international: "Tiercé international",
  e_quarte_plus_international: "Quarté+ international",
};

/** Ordre d'affichage : du pari le plus joué au plus confidentiel. */
export const ORDRE_PARIS = [
  "e_simple_gagnant",
  "e_simple_place",
  "e_couple_gagnant",
  "e_couple_place",
  "e_couple_ordre",
  "e_deux_sur_quatre",
  "e_trio",
  "e_tierce",
  "e_quarte_plus",
  "e_quinte_plus",
  "e_multi",
  "e_pick5",
];

export function libellePari(code: string): string {
  return LIBELLE_PARI[code] ?? code.replace(/^e_/, "").replace(/_/g, " ");
}

/** Trie un dictionnaire de rapports selon ORDRE_PARIS, les inconnus à la fin. */
export function rapportsTries(
  rapports: Record<string, number> | null | undefined,
): Array<[string, number]> {
  if (!rapports) return [];
  return Object.entries(rapports)
    .filter(([, v]) => typeof v === "number" && v > 0)
    .sort(([a], [b]) => {
      const ia = ORDRE_PARIS.indexOf(a);
      const ib = ORDRE_PARIS.indexOf(b);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
}

export function formatRapport(r: number): string {
  return r.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}
