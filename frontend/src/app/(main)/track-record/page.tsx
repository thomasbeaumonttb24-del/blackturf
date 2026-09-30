import { fetchTrackRecord, fetchPalmaresPublic } from "@/lib/seo";
import TrackRecordClient, { type TrackRecord } from "./TrackRecordClient";

/**
 * `/track-record` — enveloppe serveur du palmarès.
 *
 * Les deux lectures partent en parallèle au rendu serveur ; `fetchTrackRecord`
 * partage le cache de données du layout (même URL, même `revalidate`), il ne coûte
 * donc pas un second appel. Le HTML servi porte ainsi les quatre chiffres du hero
 * au lieu de cartes vides remplies une à deux secondes plus tard.
 */
export const revalidate = 60;

export default async function TrackRecordPage() {
  const [tr, palmares] = await Promise.all([fetchTrackRecord(), fetchPalmaresPublic()]);
  return (
    <TrackRecordClient
      initialTrackRecord={tr as unknown as TrackRecord | null}
      initialPalmares={palmares}
    />
  );
}
