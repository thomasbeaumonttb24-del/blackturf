/**
 * Les comptes publics de la marque — une seule déclaration.
 *
 * Trois endroits en ont besoin et doivent dire EXACTEMENT la même chose : le pied de
 * page, le balisage `Organization.sameAs` (c'est par `sameAs` que Google rattache un
 * compte social à une entité, et une adresse qui diverge d'un caractère ne rattache
 * rien), et les e-mails. Trois copies finiraient par diverger le jour d'un changement
 * de pseudonyme.
 *
 * N'ajouter ici QUE des comptes qui existent : un `sameAs` vers un profil inexistant
 * est une déclaration fausse, et elle se vérifie en un clic.
 */
export const RESEAUX = [
  {
    nom: "Instagram",
    pseudo: "@blackturf.fr",
    url: "https://www.instagram.com/blackturf.fr/",
  },
] as const;

/** Les adresses seules, pour `Organization.sameAs`. */
export const SAME_AS: string[] = RESEAUX.map((r) => r.url);

export const INSTAGRAM = RESEAUX[0];
