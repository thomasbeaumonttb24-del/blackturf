/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  compress: true,
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
    ],
    formats: ["image/avif", "image/webp"],
    minimumCacheTTL: 86400,
  },
  experimental: {
    optimizeCss: true,
  },
  headers: async () => [
    {
      source: "/(.*)",
      headers: [
        { key: "X-DNS-Prefetch-Control", value: "on" },
        { key: "X-Content-Type-Options", value: "nosniff" },
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
