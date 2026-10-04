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
  {
    nom: "TikTok",
    pseudo: "@blackturf1",
    url: "https://www.tiktok.com/@blackturf1",
  },
] as const;

/**
 * Où laisser un avis. `ecrire` mène droit au formulaire ; `profil` est la page publique
 * (déclarée dans `sameAs`). Trustpilot : fiche revendiquée blackturf.fr. Google : lien
 * « Demander des avis » donné par la fiche d'établissement, fiche Maps par son identifiant.
 */
export const AVIS = {
  trustpilot: {
    ecrire: "https://fr.trustpilot.com/evaluate/blackturf.fr",
    profil: "https://fr.trustpilot.com/review/blackturf.fr",
    // Widget « Review Collector » généré dans Trustpilot Business (TrustBox).
    templateId: "56278e9abfbbba0bdcd568bc",
    businessUnitId: "6ab1334bd0ecf7b4b35e9342",
    token: "d33f70d7-a691-4701-aace-eef6d11a7b0b",
  },
  google: {
    ecrire: "https://g.page/r/Ca-aIiYY44FdEBM/review",
    profil: "https://maps.google.com/?cid=6737916210381494959",
  },
} as const;

/** Les adresses seules, pour `Organization.sameAs`. */
export const SAME_AS: string[] = [
  ...RESEAUX.map((r) => r.url),
  AVIS.trustpilot.profil,
  AVIS.google.profil,
];

export const INSTAGRAM = RESEAUX[0];
export const TIKTOK = RESEAUX[1];
