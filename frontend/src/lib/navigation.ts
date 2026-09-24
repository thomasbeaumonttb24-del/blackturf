/**
 * Nom unique de chaque rubrique du site.
 *
 * La même page s'appelait « Nos performances » dans la barre du haut, « Palmarès » dans
 * la barre du bas sur téléphone, « Palmarès mesuré » au pied de page et « Palmarès
 * public » sur la page elle-même ; le programme s'appelait « Courses du jour »,
 * « Programme » et « Programme du jour » selon l'endroit. Un visiteur qui clique sur un
 * libellé doit retrouver ce même libellé en arrivant.
 *
 * Toute barre de navigation (haut, bas, menu mobile, pied de page, menu du compte) lit
 * ses libellés ici. `court` sert là où la place manque (barre du bas sur téléphone) ;
 * il reste le début reconnaissable du nom complet.
 */
export type Rubrique = {
  href: string;
  label: string;
  court: string;
  description: string;
};

const r = (href: string, label: string, description: string, court = label): Rubrique => ({
  href,
  label,
  court,
  description,
});

export const RUBRIQUES = {
  monEspace: r("/dashboard", "Mon espace", "Votre tableau de bord"),
  coursesDuJour: r("/programme", "Courses du jour", "Réunions, horaires et partants", "Courses"),
  quinte: r("/quinte-du-jour", "Quinté+ du jour", "La course du jour en détail", "Quinté+"),
  resultats: r("/resultats", "Résultats", "Arrivées et rapports officiels"),
  parisDeValeur: r("/value-bets", "Paris de valeur", "Chevaux mieux cotés que leur chance réelle"),
  performances: r("/track-record", "Nos performances", "Bilan mesuré de nos pronostics", "Performances"),
  tarifs: r("/tarifs", "Tarifs", "Comparer les abonnements"),
  suiviCapital: r("/bankroll", "Suivi du capital", "Votre mise et vos gains", "Capital"),
  assistant: r("/assistant", "Assistant IA", "Posez une question sur une course"),
  statistiques: r("/statistiques", "Mes statistiques", "Le bilan de vos paris"),
  strategies: r("/strategies", "Mes stratégies", "Vos règles de sélection"),
  communaute: r("/chat", "Communauté", "Le salon des membres"),
  notifications: r("/notifications", "Notifications", "Vos alertes"),
  profil: r("/profil", "Mon profil", "Compte et abonnement"),
  methode: r("/pronostics-ia", "Comment marche l’IA", "Notre méthode expliquée"),
} as const satisfies Record<string, Rubrique>;
