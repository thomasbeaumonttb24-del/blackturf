import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Toaster } from "sonner";
import { AuthProvider } from "@/hooks/useAuth";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: {
    default: "BlackTurf — Votre Conseiller Expert en Paris Hippiques",
    template: "%s | BlackTurf",
  },
  description:
    "Entrez votre mise → BlackTurf génère votre plan de pari personnalisé. Un algorithme propulsé par l'IA (XGBoost + LightGBM + CatBoost) qui se réentraîne après chaque course sur les résultats réels du PMU.",
  keywords: [
    "pronostics hippiques", "pari de valeur", "intelligence artificielle",
    "PMU", "analyse hippique", "tiercé", "quinté", "critère de Kelly",
    "conseiller paris", "capital hippique",
  ],
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
    title: "BlackTurf — Votre Conseiller Expert en Paris Hippiques",
    description:
      "Plan de mise personnalisé. Paris de valeur détectés par IA. Programme PMU du jour analysé.",
    images: [{ url: "/og-image.jpg", width: 1200, height: 630, alt: "BlackTurf" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "BlackTurf — Le moteur qui réapprend chaque course",
    description: "Plan de mise personnalisé. Paris de valeur en temps réel.",
  },
  robots: { index: true, follow: true },
  alternates: { canonical: "/" },
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
