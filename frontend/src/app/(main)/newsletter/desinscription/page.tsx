import type { Metadata } from "next";
import Link from "next/link";
import { Container, SeoHero } from "@/components/seo/kit";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Désinscription",
  robots: { index: false, follow: false },
};

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

async function desinscrire(jeton: string): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(
      `${API}/newsletter/desinscription?jeton=${encodeURIComponent(jeton)}`,
      { cache: "no-store" },
    );
    if (!res.ok) return { ok: false, message: "Ce lien de désinscription n'est plus valable." };
    return (await res.json()) as { ok: boolean; message: string };
  } catch {
    return { ok: false, message: "Le service ne répond pas. Réessayez dans un instant." };
  }
}

export default async function DesinscriptionPage({
  searchParams,
}: {
  searchParams: Promise<{ jeton?: string }>;
}) {
  const { jeton } = await searchParams;
  const resultat = jeton
    ? await desinscrire(jeton)
    : { ok: false, message: "Lien incomplet : le jeton de désinscription manque." };

  return (
    <>
      <SeoHero
        eyebrow="Lettre hebdomadaire"
        title={resultat.ok ? "Désinscription enregistrée" : "Désinscription impossible"}
        lead={resultat.message}
      />
      <Container>
        <p className="text-sm leading-relaxed text-brand-charcoal/85">
          {resultat.ok
            ? "Plus aucun envoi ne partira vers cette adresse. Le site reste évidemment accessible sans inscription."
            : "Si le lien vient d'un e-mail ancien, ouvrez celui de la dernière lettre reçue : chaque envoi contient un lien valable."}{" "}
          <Link href="/programme" className="font-medium text-brand-gold-deep hover:underline">
            Programme du jour
          </Link>{" "}
          ·{" "}
          <Link href="/resultats" className="font-medium text-brand-gold-deep hover:underline">
            Arrivées et rapports
          </Link>
        </p>
      </Container>
    </>
  );
}
