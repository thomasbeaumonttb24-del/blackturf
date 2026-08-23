import { publicationsDuJour } from "@/lib/visuels-legendes";

// Consommée par le service de publication du backend. Publique et sans secret : elle ne
// contient que ce qui finira de toute façon dans une publication ouverte.
export const revalidate = 300;

export async function GET() {
  return Response.json(
    { publications: await publicationsDuJour() },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
