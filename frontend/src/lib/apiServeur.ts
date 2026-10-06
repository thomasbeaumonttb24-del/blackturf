/*
 * Adresse de l'API pour les lectures faites CÔTÉ SERVEUR (composants serveur, route
 * handlers de /visuels, lib/seo.ts…). Ne jamais s'en servir pour un appel du navigateur.
 *
 * Pourquoi un chemin à part : `NEXT_PUBLIC_API_URL` pointe sur le domaine public. Le
 * rendu serveur de TOUTES les pages repassait donc par nginx, sous une seule adresse —
 * celle de la passerelle Docker — et partageait un seul seau de quota (limit_req nginx
 * + `rate_limit_public` de l'API, par IP). Un client qui bouclait sur une route publique
 * rendue côté serveur vidait ce seau : chaque lecture SSR prenait un 429, les pages
 * sortaient vides pour tout le monde, puis restaient vides en cache ISR.
 *
 * En production, `API_URL_INTERNE` (http://api:8000) fait sortir ces lectures par le
 * réseau Docker, sans nginx, et `BT_SECRET_INTERNE` les fait reconnaître par l'API, qui
 * ne les compte plus dans ses quotas par IP.
 *
 * Le secret ne peut pas atteindre le navigateur : Next n'inline dans le bundle client
 * QUE les variables `NEXT_PUBLIC_*`. Ce module est pourtant tiré dans le bundle client
 * par ricochet (des composants client importent des utilitaires de lib/seo.ts) — d'où
 * la garde `typeof window` plutôt qu'un `throw` à l'import : côté navigateur il rend
 * simplement l'URL publique et aucun en-tête. Le paquet `server-only` n'est pas installé.
 */

const COTE_NAVIGATEUR = typeof window !== "undefined";

/** Origine de l'API (sans `/api/v1`) pour un appel serveur. */
export function apiServeurOrigine(defaut = "https://api.blackturf.fr"): string {
  // Lue à l'APPEL et non figée au build : `API_URL_INTERNE` n'est fournie qu'au runtime
  // du conteneur (docker-compose), jamais en argument de build.
  const interne = COTE_NAVIGATEUR ? "" : (process.env.API_URL_INTERNE || "").trim();
  return (interne || process.env.NEXT_PUBLIC_API_URL || defaut).replace(/\/+$/, "");
}

/** Préfixe `/api/v1` des lectures serveur. */
export function apiServeurV1(defaut?: string): string {
  return `${apiServeurOrigine(defaut)}/api/v1`;
}

/** En-têtes à joindre à toute lecture serveur de l'API (vide si le secret est absent). */
export function entetesServeur(): Record<string, string> {
  if (COTE_NAVIGATEUR) return {};
  const secret = (process.env.BT_SECRET_INTERNE || "").trim();
  return secret ? { "X-BT-Interne": secret } : {};
}

/** `init` de fetch complété des en-têtes serveur (ceux passés par l'appelant gardent la main). */
export function initServeur<T extends RequestInit>(init?: T): T {
  const base = (init ?? {}) as T;
  return {
    ...base,
    headers: { ...entetesServeur(), ...((base.headers as Record<string, string> | undefined) ?? {}) },
  };
}

/**
 * Erreur levée quand l'API répond 429 ou 5xx à une lecture serveur.
 *
 * Renvoyer `null` dans ce cas rendait une page VIDE que Next gardait ensuite en cache
 * ISR pour toute sa durée de revalidation. Lever à la place fait échouer la
 * revalidation : Next continue de servir la dernière bonne version. Un 404 n'est PAS
 * concerné — « cette course n'existe pas » est une réponse, pas une panne.
 */
export class ApiServeurIndisponible extends Error {
  constructor(public readonly statut: number, url: string) {
    super(`API ${statut} sur ${url}`);
    this.name = "ApiServeurIndisponible";
  }
}

/**
 * Lève `ApiServeurIndisponible` sur 429/5xx, sauf pendant `next build`.
 *
 * Au build, une API momentanément indisponible ferait échouer TOUT le déploiement pour
 * une page dont la version vide sera de toute façon régénérée à la première visite : on
 * garde alors l'ancien comportement (l'appelant retombe sur sa valeur vide).
 */
export function leverSiTransitoire(res: Response, url: string): void {
  if (res.status !== 429 && res.status < 500) return;
  if (enBuild()) return;
  throw new ApiServeurIndisponible(res.status, url);
}

/**
 * À appeler en tête d'un `catch` qui rendait jusqu'ici une valeur vide.
 *
 * Relance `ApiServeurIndisponible`, et traite de même l'API INJOIGNABLE (undici lève
 * `TypeError: fetch failed` — conteneur api en cours de redémarrage pendant un
 * déploiement, typiquement) : c'est la même panne passagère, qui ne doit pas davantage
 * figer une page vide en cache. Toute autre erreur (JSON illisible…) est laissée à
 * l'appelant, qui garde son repli.
 */
export function relancerSiTransitoire(e: unknown): void {
  if (e instanceof ApiServeurIndisponible) throw e;
  if (!enBuild() && e instanceof TypeError && /fetch failed/i.test(e.message)) {
    throw new ApiServeurIndisponible(0, `réseau (${e.message})`);
  }
}

function enBuild(): boolean {
  return process.env.NEXT_PHASE === "phase-production-build";
}
