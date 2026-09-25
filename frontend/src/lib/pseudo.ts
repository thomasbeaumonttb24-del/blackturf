import { z } from "zod";

/**
 * Pseudo public (classement du Défi du mois, Communauté). Mêmes règles que le
 * serveur (backend/services/pseudo.py) : les vérifier ici évite un aller-retour
 * pour une faute de format, le serveur reste seul juge de l'unicité.
 */
export const PSEUDO_RE = /^[A-Za-z0-9À-ÖØ-öø-ÿ_.-]{3,20}$/;
export const PSEUDO_AIDE = "3 à 20 caractères : lettres, chiffres, point, tiret ou soulignement.";

export const champPseudo = z
  .string()
  .trim()
  .regex(PSEUDO_RE, PSEUDO_AIDE);
