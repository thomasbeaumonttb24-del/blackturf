import { visuelQuinte, enJpeg } from "@/lib/visuels-rendu";

// L'extension `.jpg` est dans le CHEMIN à dessein : l'API de publication Instagram va
// chercher l'image elle-même et n'accepte que du JPEG. Une URL qui se termine par .jpg
// évite aussi toute ambiguïté quand le lien est partagé à la main.
export const revalidate = 900;

export async function GET() {
  return enJpeg(await visuelQuinte());
}
