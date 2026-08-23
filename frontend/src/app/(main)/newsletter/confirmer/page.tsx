import type { Metadata } from "next";
import Link from "next/link";
import { Container, SeoHero } from "@/components/seo/kit";

// Page à jeton : jamais mise en cache, jamais indexée. Une URL de confirmation qui
// figurerait dans l'index exposerait le jeton d'un inscrit.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Confirmation d'inscription",
  robots: { index: false, follow: false },
};

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

async function confirmer(jeton: string): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(
      `${API}/newsletter/confirmer?jeton=${encodeURIComponent(jeton)}`,
      { cache: "no-store" },
    );
    if (!res.ok) return { ok: false, message: "Ce lien de confirmation n'est plus valable." };
    return (await res.json()) as { ok: boolean; message: string };
  } catch {
    // Panne réseau : surtout ne pas annoncer un lien invalide, l'inscription est
    // peut-être parfaitement valide et la personne renoncerait pour rien.
    return { ok: false, message: "Le service ne répond pas. Réessayez dans un instant." };
  }
}

export default async function ConfirmerPage({
  searchParams,
}: {
  searchParams: Promise<{ jeton?: string }>;
}) {
  const { jeton } = await searchParams;
  const resultat = jeton
    ? await confirmer(jeton)
    : { ok: false, message: "Lien incomplet : le jeton de confirmation manque." };

  return (
    <>
      <SeoHero
        eyebrow="Lettre hebdomadaire"
        title={resultat.ok ? "C'est confirmé" : "Confirmation impossible"}
        lead={resultat.message}
      />
      <Container>
        {resultat.ok ? (
          <p className="text-sm leading-relaxed text-brand-charcoal/85">
            Vous recevrez la première lettre lundi matin : le bilan chiffré de la semaine,
            gains comme pertes. En attendant, le{" "}
            <Link href="/programme" className="font-medium text-brand-gold-deep hover:underline">
              programme du jour
            </Link>{" "}
            et les{" "}
            <Link href="/resultats" className="font-medium text-brand-gold-deep hover:underline">
              arrivées et rapports
            </Link>{" "}
            sont en accès libre.
          </p>
        ) : (
          <p className="text-sm leading-relaxed text-brand-charcoal/85">
            Un lien de confirmation ne sert qu&apos;une fois, et une nouvelle demande
            d&apos;inscription annule le précédent. Si vous êtes déjà confirmé, il n&apos;y a
            rien à faire. Sinon,{" "}
            <Link href="/newsletter" className="font-medium text-brand-gold-deep hover:underline">
              redemandez un lien
            </Link>
            .
          </p>
        )}
      </Container>
    </>
  );
}
