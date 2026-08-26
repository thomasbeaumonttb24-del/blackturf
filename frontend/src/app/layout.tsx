import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Toaster } from "sonner";
import { AuthProvider } from "@/hooks/useAuth";

// « latin-ext » en plus de « latin » : les partants PMU portent des noms étrangers
// (roumains, polonais, scandinaves) dont les lettres sortent du bloc latin de base. Ces
// noms n'arrivent qu'APRÈS l'hydratation — le HTML rendu côté serveur n'en contient
// aucun. Le navigateur découvrait donc la sous-police latin-ext trop tard, la
// substituait en cours de route et faisait reflower tout le bloc : 0,303 de CLS sur la
// page course, à elle seule 21 points de performance. Déclarer le sous-ensemble le fait
// précharger avec le reste.
const inter = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin", "latin-ext"],
  variable: "--font-space-grotesk",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: {
    default: "BlackTurf — pronostics PMU notés aux rapports réels",
    // Pas de gabarit « %s | BlackTurf » : Google affiche déjà « blackturf.fr » comme nom
    // de site au-dessus du titre. Le suffixe répétait donc la marque une seconde fois et
    // mangeait la largeur disponible sur mobile, là où le titre est tronqué.
    template: "%s",
  },
  // Google tronque autour de 155-160 caractères : l'essentiel passe devant.
  description:
    "Programme PMU du jour, probabilité calculée pour chaque cheval et plan de mise ajusté à votre budget. Chaque pronostic est noté aux rapports réels du PMU.",
  // `meta keywords` est ignorée par Google depuis 2009 — retirée.
  metadataBase: new URL("https://blackturf.fr"),
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "BlackTurf",
  },
  openGraph: {
    type: "website",
    locale: "fr_FR",
    url: "https://blackturf.fr",
    siteName: "BlackTurf",
    // Aligné sur le <title> : og:title est une des sources dont Google se sert pour
    // fabriquer le lien de titre, une divergence l'empêche de trancher.
    title: "BlackTurf — pronostics PMU notés aux rapports réels",
    description:
      "Programme PMU du jour, probabilité par cheval et plan de mise sur votre budget. Pronostics notés aux rapports réels.",
    images: [{ url: "/og-image.jpg", width: 1200, height: 630, alt: "BlackTurf" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "BlackTurf — pronostics PMU notés aux rapports réels",
    description: "Programme PMU du jour, probabilité par cheval, plan de mise sur votre budget.",
  },
  robots: { index: true, follow: true },
  // Pas de canonical global : `alternates` est HÉRITÉ par toute page qui ne le redéfinit
  // pas. Un canonical "/" posé ici faisait déclarer à /programme et à chaque /courses/<id>
  // qu'elles étaient des doublons de l'accueil — Google les fusionnait avec la home au lieu
  // de les indexer. Chaque page pose désormais SON propre canonical.
};

// Données structurées globales (organisation + site) → éligibilité rich results / sitelinks.
const orgJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "BlackTurf",
  url: "https://blackturf.fr",
  logo: "https://blackturf.fr/logo.png",
  description:
    "Conseiller IA en paris hippiques PMU : plan de mise personnalisé et paris de valeur, réentraîné après chaque course.",
};
const siteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "BlackTurf",
  // Variante réellement tapée par les visiteurs (29 impressions sur « black turf » en
  // 90 jours) : alternateName permet à Google de rattacher les deux au même site.
  alternateName: "Black Turf",
  url: "https://blackturf.fr",
  inLanguage: "fr-FR",
  potentialAction: {
    "@type": "SearchAction",
    target: "https://blackturf.fr/recherche?q={search_term_string}",
    "query-input": "required name=search_term_string",
  },
};

export const viewport: Viewport = {
  themeColor: "#F59E0B",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className={`${inter.variable} ${spaceGrotesk.variable} font-sans antialiased min-h-screen bg-background`}>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(orgJsonLd) }} />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd) }} />
        <AuthProvider>{children}</AuthProvider>
        <Toaster
          theme="light"
          position="top-right"
          toastOptions={{
            style: {
              background: "#FFFFFF",
              border: "1px solid #E5E7EB",
              color: "#111827",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
            },
            classNames: {
              success: "!border-emerald-200",
              error: "!border-red-200",
              warning: "!border-amber-300",
            },
          }}
        />
        {/* Service Worker registration */}
        <Script id="sw-register" strategy="lazyOnload">{`
          if ('serviceWorker' in navigator) {
            window.addEventListener('load', function() {
              navigator.serviceWorker.register('/sw.js').then(function(reg) {
                console.log('[BlackTurf] SW registered:', reg.scope);
              }).catch(function(err) {
                console.warn('[BlackTurf] SW registration failed:', err);
              });
            });
          }
        `}</Script>
      </body>
    </html>
  );
}
