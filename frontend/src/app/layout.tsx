import type { Metadata, Viewport } from "next";
import { jsonLd } from "@/lib/seo";
import { Inter, Space_Grotesk } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Toaster } from "sonner";
import { AuthProvider } from "@/hooks/useAuth";
import { Suspense } from "react";
import DefilementHaut from "@/components/DefilementHaut";

// `display: "optional"` plutôt que `"swap"`, et on s'en tient au sous-ensemble `latin`.
//
// Le problème d'origine : les partants PMU portent des noms étrangers (roumains,
// polonais, scandinaves) dont les lettres sortent du bloc latin de base. Ces noms
// n'arrivent qu'APRÈS l'hydratation — le HTML rendu côté serveur n'en contient aucun. Le
// navigateur découvrait donc la sous-police latin-ext en cours de route, la substituait,
// et faisait reflower tout le bloc : 0,303 de CLS sur la page course.
//
// Première tentative : déclarer `latin-ext` pour le faire précharger. Corrigeait bien le
// CLS, mais MESURÉ ensuite : le préchargement passait de 69 ko à 171 ko (Inter latin-ext
// pèse 83 ko à lui seul), en priorité maximale sur le chemin critique. À 1,6 Mbit/s c'est
// +510 ms — et le premier rendu de /quinte-du-jour passait de 0,9 s à 1,7 s sur mobile.
// Un CLS réparé sur une page contre un demi-seconde perdue sur toutes : mauvais échange.
//
// `optional` supprime la période de substitution : une police qui arrive en retard n'est
// jamais appliquée, donc plus aucun décalage possible — ni depuis latin-ext, ni depuis
// latin. Et on ne précharge plus que les 69 ko utiles. Contrepartie assumée : sur une
// première visite en connexion lente, le texte s'affiche dans la police de repli. Elle
// est ajustée par next/font (`size-adjust`, `ascent-override`) sur les métriques de la
// vraie police, donc la mise en page est identique au pixel près.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "optional",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "optional",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: {
    // « IA » figure au titre parce que c'est littéralement ce que fait le site : un modèle
    // statistique réentraîné chaque nuit calcule une probabilité par cheval. Le mot était
    // absent du titre comme du h1, alors que le champ lexical revenait trente-cinq fois
    // dans le corps de la page — la page traitait le sujet sans jamais le dire.
    default: "BlackTurf — pronostics PMU par IA, notés aux rapports réels",
    // Pas de gabarit « %s | BlackTurf » : Google affiche déjà « blackturf.fr » comme nom
    // de site au-dessus du titre. Le suffixe répétait donc la marque une seconde fois et
    // mangeait la largeur disponible sur mobile, là où le titre est tronqué.
    template: "%s",
  },
  // Google tronque autour de 155-160 caractères : l'essentiel passe devant.
  description:
    "Programme PMU analysé par IA : une probabilité par cheval et un plan de mise ajusté à votre budget. Pronostics notés aux rapports réels du PMU.",
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
    title: "BlackTurf — pronostics PMU par IA, notés aux rapports réels",
    description:
      "Programme PMU du jour analysé par IA : probabilité par cheval et plan de mise sur votre budget. Pronostics notés aux rapports réels.",
    images: [{ url: "/og-image.jpg", width: 1200, height: 630, alt: "BlackTurf" }],
  },
  // Volontairement réduite à la seule forme de carte.
  //
  // Un `twitter` complet posé ici était HÉRITÉ par toutes les pages qui ne le
  // redéfinissaient pas — c'est-à-dire presque toutes. Partager une fiche course ou une
  // journée de résultats affichait donc « BlackTurf — pronostics PMU notés aux rapports
  // réels », le titre de l'accueil, quelle que soit la page. En ne déclarant que `card`,
  // les réseaux retombent sur les balises Open Graph de la page elle-même, qui sont
  // exactes : c'est le comportement de repli prévu par leur spécification, et cela évite
  // de maintenir deux fois le même texte.
  twitter: { card: "summary_large_image" },
  robots: { index: true, follow: true },
  // Pas de canonical global : `alternates` est HÉRITÉ par toute page qui ne le redéfinit
  // pas. Un canonical "/" posé ici faisait déclarer à /programme et à chaque /courses/<id>
  // qu'elles étaient des doublons de l'accueil — Google les fusionnait avec la home au lieu
  // de les indexer. Chaque page pose désormais SON propre canonical.
};

// Données structurées globales (organisation + site) → éligibilité rich results / sitelinks.
//
// L'entité était réduite au nom, à l'URL et au logo, alors que /mentions-legales publie
// déjà l'éditeur nommé, son SIREN, son adresse et son contact. Sur un sujet d'argent, ces
// éléments sont précisément ce qui permet à Google de rattacher le site à une entité
// réelle et identifiable plutôt qu'à une marque anonyme. Tout ce qui est déclaré ici est
// visible sur la page des mentions légales : rien n'est balisé qui ne soit publié.
const orgJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "BlackTurf",
  legalName: "Thomas Beaumont (entreprise individuelle)",
  url: "https://blackturf.fr",
  logo: "https://blackturf.fr/logo.png",
  image: "https://blackturf.fr/og-image.jpg",
  description:
    "Conseiller IA en paris hippiques PMU : plan de mise personnalisé et paris de valeur, réentraîné après chaque course.",
  foundingDate: "2025-04-01",
  founder: { "@type": "Person", name: "Thomas Beaumont" },
  address: {
    "@type": "PostalAddress",
    streetAddress: "10 rue Alix d'Unienville",
    postalCode: "33100",
    addressLocality: "Bordeaux",
    addressCountry: "FR",
  },
  contactPoint: {
    "@type": "ContactPoint",
    contactType: "customer support",
    email: "contact@blackturf.fr",
    availableLanguage: ["fr"],
  },
  // Identifiant d'entreprise français : c'est la référence vérifiable auprès d'un tiers.
  identifier: { "@type": "PropertyValue", propertyID: "SIREN", value: "907548184" },
  areaServed: "FR",
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
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(orgJsonLd) }} />
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(siteJsonLd) }} />
        {/* Toute page s'ouvre en haut. Sous Suspense : `useSearchParams`
            basculerait sinon l'ensemble du site en rendu dynamique. */}
        <Suspense fallback={null}>
          <DefilementHaut />
        </Suspense>
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
