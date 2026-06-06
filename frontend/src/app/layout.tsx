import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Toaster } from "sonner";

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
    "Entrez votre mise → BlackTurf génère votre plan de pari personnalisé. Paris de valeur détectés par IA en temps réel. XGBoost + LightGBM + CatBoost. Précision Top-3 : 59%. Rendement simulé : +8,4%.",
  keywords: [
    "pronostics hippiques", "pari de valeur", "intelligence artificielle",
    "PMU", "analyse hippique", "tiercé", "quinté", "critère de Kelly",
    "conseiller paris", "capital hippique",
  ],
  metadataBase: new URL("https://blackturf.fr"),
  manifest: "/manifest.json",
  themeColor: "#F59E0B",
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
    title: "BlackTurf — IA Hippique",
    description: "Plan de mise personnalisé. Paris de valeur en temps réel.",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="apple-touch-icon" href="/icons/icon-192.png" />
      </head>
      <body className={`${inter.variable} ${spaceGrotesk.variable} font-sans antialiased min-h-screen bg-background`}>
        {children}
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
