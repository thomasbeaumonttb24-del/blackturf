/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  compress: true,
  // Fenêtre de péremption des pages ISR. Par défaut Next annonce
  // `stale-while-revalidate=31535940`, soit un an : le cache du navigateur a alors le
  // droit de resservir un HTML vieux d'une journée entière et de ne le rafraîchir qu'en
  // arrière-plan. Sur /programme, dont le contenu ET le titre portent une date, cela
  // rouvrait la page d'hier — jusqu'à ce qu'une seconde visite montre enfin celle du
  // jour. Cinq minutes de péremption alignent le cache HTTP sur le `revalidate = 300`
  // déjà déclaré par les pages datées ; le cache serveur, lui, ne change pas.
  expireTime: 300,
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
    ],
    formats: ["image/avif", "image/webp"],
    minimumCacheTTL: 86400,
  },
  experimental: {
    // `optimizeCss` a été retiré : il était déclaré depuis longtemps et ne produisait
    // RIEN. Vérifié dans le code de Next — `postProcessHTML`, seul endroit qui appelle
    // critters, n'est importé que par `server/render.js`, le rendu du routeur Pages.
    // L'App Router ne passe jamais par là. Confirmé côté sortie : le HTML de production
    // comme le HTML prérendu en local sortent avec deux <link rel="stylesheet"> et zéro
    // <style> inline, pendant que la feuille de 19 ko bloque le rendu ~600 ms sur chaque
    // page en mobile.
    //
    // `inlineCss` (l'équivalent App Router) a été ESSAYÉ en production le 26/08 puis
    // retiré, sur mesure. Il fait bien ce qu'il annonce — plus aucun <link rel=stylesheet>,
    // un seul <style> — mais il ne rapporte rien ici :
    //   /tarifs           15,3 ko de HTML + 19,4 ko de CSS gzip en 2 requêtes
    //                  -> 55,3 ko de HTML gzip en 1 requête, soit +20,6 ko
    // Le CSS est dupliqué, une fois dans <style> et une fois dans la charge RSC — c'est
    // une limitation documentée du drapeau. Les +100 ms de transfert à 1,6 Mbit/s annulent
    // l'aller-retour économisé. Mesuré sur 3 passages PageSpeed par page : accueil est
    // même passé de 1,1 s à 1,7 s de premier rendu, quinté de 99 à 91-97, la page course
    // n'a pas bougé. À quoi s'ajoute une contrepartie certaine, elle : le CSS n'est plus
    // mis en cache entre les pages, alors qu'un visiteur enchaîne programme → course →
    // course. Ne pas le réactiver sans remesurer.
    //
    // Barils d'icônes et de graphiques : n'embarquer que les symboles réellement
    // importés au lieu du module entier (24 ko de JS inutilisé relevés sur l'accueil).
    optimizePackageImports: ["lucide-react", "recharts", "date-fns"],
  },
  headers: async () => [
    {
      source: "/(.*)",
      headers: [
        { key: "X-DNS-Prefetch-Control", value: "on" },
        { key: "X-Content-Type-Options", value: "nosniff" },
      ],
    },
    {
      // Tout ce qui vient de /public sort par défaut en `Cache-Control: public, max-age=0`
      // — Next ne peut pas deviner si le fichier changera sous le même nom. Résultat :
      // l'image du hero (178 ko), qui est l'élément LCP de l'accueil, était retéléchargée
      // à CHAQUE visite, deuxième visite comprise. Ces fichiers sont versionnés par leur
      // nom dans le projet (hero-1024.webp, attele-v6.png…) : un mois de cache avec
      // revalidation en arrière-plan est sans risque, et une mise à jour passe de toute
      // façon par un nouveau nom de fichier.
      source: "/:dossier(img|icons)/:chemin*",
      headers: [
        { key: "Cache-Control", value: "public, max-age=2592000, stale-while-revalidate=86400" },
      ],
    },
    {
      source: "/:fichier(logo.png|og-image.jpg|favicon.ico)",
      headers: [
        { key: "Cache-Control", value: "public, max-age=2592000, stale-while-revalidate=86400" },
      ],
    },
  ],
  async redirects() {
    return [
      // /courses n'a jamais eu de page : Google l'a pourtant indexée (via les liens vers
      // /courses/<id>) et servait donc un 404 aux visiteurs. Le hub des courses, c'est le
      // programme du jour.
      { source: "/courses", destination: "/programme", permanent: true },
      // Variantes tapées à la main / vues dans les liens entrants.
      { source: "/quinte", destination: "/quinte-du-jour", permanent: true },
      { source: "/resultats-pmu", destination: "/resultats", permanent: true },
      { source: "/arrivees", destination: "/resultats", permanent: true },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
