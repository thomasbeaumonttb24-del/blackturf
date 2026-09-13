/**
 * Les octets d'un visuel au moment où le job de publication les a VALIDÉS.
 *
 * INCIDENT DU 2026-09-13 : la tuile hebdomadaire n'est jamais partie. Meta va chercher
 * l'image lui-même, et une tuile se compose à la demande — 8,5 s depuis que les routes
 * publiées lisent l'API sans cache (story à « 0 € » du 2026-09-10). Meta abandonnait
 * avant la fin (nginx : 499) et refusait le conteneur : « Media download has failed »,
 * six passages de suite, sans rien publier.
 *
 * Le job télécharge donc l'image LUI-MÊME d'abord, sur une URL portant une clé d'envoi
 * unique (`?envoi=<hex>`), vérifie que c'est bien un JPEG, puis donne CETTE URL à Meta.
 * La route garde les octets rendus sous cette clé quelques minutes : Meta reçoit
 * l'image immédiatement, et c'est exactement celle que le job a validée.
 *
 * Ce n'est PAS le cache interdit par l'incident du 2026-09-11 : aucune donnée n'y est
 * lue, et une clé ne peut être remplie que par la requête qui la porte — une visite du
 * studio la veille ne peut pas y déposer une image périmée. Sans `envoi`, rien n'est
 * gardé ni relu.
 */

const DUREE_MS = 15 * 60 * 1000;
const MAX_ENVOIS = 24;

type Envoi = { corps: Uint8Array; type: string; expire: number };

const envois = new Map<string, Envoi>();

/** La clé d'envoi portée par l'URL, ou `null` si la requête n'en porte pas. */
export function cleEnvoi(url: string): string | null {
  try {
    const u = new URL(url);
    const envoi = u.searchParams.get("envoi");
    if (!envoi || !/^[a-f0-9]{16,64}$/.test(envoi)) return null;
    // Chemin + paramètres, sans l'hôte : le job passe par le domaine public, et la
    // requête arrive au serveur Next sous son adresse interne.
    return `${u.pathname}?${u.searchParams.toString()}`;
  } catch {
    return null;
  }
}

/** L'image déjà rendue pour cet envoi, ou `null` s'il faut la composer. */
export function envoiGarde(cle: string | null): Response | null {
  if (!cle) return null;
  const e = envois.get(cle);
  if (!e) return null;
  if (e.expire < Date.now()) {
    envois.delete(cle);
    return null;
  }
  return new Response(new Uint8Array(e.corps), {
    headers: { "Content-Type": e.type, "Cache-Control": "no-store" },
  });
}

/** Garde l'image rendue pour la requête de Meta qui suit. Sans clé, ne fait rien. */
export function garderEnvoi(cle: string | null, corps: Uint8Array, type: string): void {
  if (!cle) return;
  const maintenant = Date.now();
  for (const [k, e] of envois) {
    if (e.expire < maintenant) envois.delete(k);
  }
  while (envois.size >= MAX_ENVOIS) {
    const plusAncien = envois.keys().next().value;
    if (plusAncien === undefined) break;
    envois.delete(plusAncien);
  }
  envois.set(cle, { corps, type, expire: maintenant + DUREE_MS });
}
