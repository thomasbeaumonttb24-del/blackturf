import { visuelArrivee, enJpeg } from "@/lib/visuels-rendu";

export const revalidate = 300;

export async function GET() {
  return enJpeg(await visuelArrivee());
}
