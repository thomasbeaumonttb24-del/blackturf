import { z } from "zod";

/**
 * Règle de mot de passe — miroir EXACT de la politique du backend
 * (`RegisterRequest._password_strength` et `reset_password` dans
 * `backend/api/routes/auth.py`).
 *
 * Elle vit ici parce que les deux formulaires (inscription et
 * réinitialisation) la dupliquaient en annonçant « 8 caractères minimum »
 * alors que l'API en exige 10 et refuse un mot de passe composé
 * uniquement de lettres ou uniquement de chiffres. Le visiteur passait
 * la validation du navigateur, recevait un HTTP 422, et voyait le
 * message brut de Pydantic — en anglais — sous un champ qui venait de
 * lui promettre que 8 suffisaient. Mesuré en production le 02/09/2026 :
 * trois tentatives en 23 secondes depuis la même adresse, aucun compte
 * créé.
 *
 * Toute modification de la politique côté API doit être répercutée ici,
 * et l'inverse : `MOT_DE_PASSE_AIDE` est le texte affiché AVANT la
 * saisie, pour que la contrainte ne se découvre pas à l'envoi.
 */
export const MOT_DE_PASSE_MIN = 10;
export const MOT_DE_PASSE_AIDE = "10 caractères minimum, avec au moins une lettre et un chiffre";

// `isalpha()` / `isdigit()` de Python raisonnent en Unicode : « Motdepasse »
// est refusé, « Mötdepassé » aussi. On reproduit la même portée avec \p{L}.
const QUE_DES_LETTRES = /^\p{L}+$/u;
const QUE_DES_CHIFFRES = /^\p{Nd}+$/u;

export const champMotDePasse = z
  .string()
  .min(MOT_DE_PASSE_MIN, `${MOT_DE_PASSE_MIN} caractères minimum`)
  .max(128, "128 caractères maximum")
  .refine((v) => !QUE_DES_LETTRES.test(v) && !QUE_DES_CHIFFRES.test(v), {
    message: "Mélangez lettres et chiffres",
  });

/**
 * Traduit ce que l'API renvoie quand un mot de passe la traverse quand même
 * (collage depuis un gestionnaire, formulaire rempli avant un déploiement,
 * client tiers). Sans cette table, l'utilisateur lit « String should have at
 * least 10 characters » sur un site en français.
 */
export function messageErreurApi(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return undefined;

  const messages = detail
    .map((d) => {
      const item = d as { msg?: string; type?: string; loc?: unknown[] };
      const champ = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : "";
      if (champ === "password") {
        if (item.type === "string_too_short") return `Mot de passe : ${MOT_DE_PASSE_AIDE}.`;
        if (item.type === "string_too_long") return "Mot de passe : 128 caractères maximum.";
      }
      if (champ === "email") return "Adresse e-mail invalide.";
      // `value_error` porte déjà le texte français du validateur, préfixé par
      // Pydantic ; on retire le préfixe plutôt que d'inventer un message.
      return item.msg?.replace(/^Value error,\s*/, "");
    })
    .filter(Boolean);

  return messages.length ? messages.join(" ") : undefined;
}
