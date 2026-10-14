import Image from "next/image";
import photos from "@/lib/photosHippodromes.json";

export interface CreditPhoto {
  fichier: string;
  auteur: string;
  licence: string;
  licence_url: string;
  source: string;
  largeur: number;
  hauteur: number;
}

const PHOTOS = photos as Record<string, CreditPhoto>;

export function photoHippodrome(slug: string): CreditPhoto | null {
  return PHOTOS[slug] ?? null;
}

/**
 * Photo réelle du lieu, en tête de fiche. Les photos viennent de Wikimedia Commons,
 * sous licence libre (CC0, CC BY, CC BY-SA) : le crédit — auteur, licence, lien vers
 * la source — est une obligation de la licence, il reste toujours visible.
 */
export function PhotoLieu({ photo, alt }: { photo: CreditPhoto; alt: string }) {
  return (
    <div className="mt-8">
      <div className="relative overflow-hidden rounded-3xl border border-white/60 shadow-[0_24px_60px_-20px_rgba(28,25,23,0.45)]">
        <Image
          src={photo.fichier}
          alt={alt}
          width={photo.largeur}
          height={photo.hauteur}
          sizes="(min-width: 1024px) 960px, 100vw"
          loading="eager"
          fetchPriority="high"
          className="aspect-[16/9] h-auto w-full object-cover sm:aspect-[21/9]"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-stone-950/35 via-transparent to-transparent" />
        <p className="absolute right-2 top-2 max-w-[85%] rounded-full bg-stone-950/80 px-2.5 py-1 text-right text-[10.5px] leading-tight text-white/90 backdrop-blur-sm">
          Photo :{" "}
          <a href={photo.source} target="_blank" rel="noopener" className="underline-offset-2 hover:underline">
            {photo.auteur}
          </a>
          {photo.licence && (
            <>
              {" "}·{" "}
              {photo.licence_url ? (
                <a href={photo.licence_url} target="_blank" rel="noopener license" className="underline-offset-2 hover:underline">
                  {photo.licence}
                </a>
              ) : (
                photo.licence
              )}
            </>
          )}
          {" "}· Wikimedia Commons
        </p>
      </div>
    </div>
  );
}
