import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // BlackTurf v4 — Blanc Premium × Or
        brand: {
          gold: "#F59E0B",
          "gold-deep": "#D97706",
          "gold-dark": "#B45309",
          "gold-light": "#FFFBEB",
          "gold-tint": "#FEF3C7",
          dark: "#111827",
          charcoal: "#374151",
          emerald: "#059669",
          "emerald-dark": "#047857",
          red: "#DC2626",
          blue: "#2563EB",
          amber: "#FCD34D",
          cream: "#FFFBF0",
          warm: "#FAFAF8",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-in-out",
        "slide-up": "slideUp 0.4s ease-out",
        "pulse-slow": "pulse 3s ease-in-out infinite",
        "bounce-light": "bounce 1s ease-in-out 3",
        "glow-gold": "glowGold 2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(20px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        glowGold: {
          "0%, 100%": { boxShadow: "0 0 8px rgba(245,158,11,0.25)" },
          "50%":       { boxShadow: "0 0 20px rgba(245,158,11,0.50)" },
        },
      },
      backgroundImage: {
        "gradient-gold": "linear-gradient(135deg, #B45309 0%, #D97706 50%, #F59E0B 100%)",
        "gradient-gold-soft": "linear-gradient(135deg, #FEF3C7 0%, #FCD34D 100%)",
        "gradient-emerald": "linear-gradient(135deg, #059669 0%, #34D399 100%)",
        "gradient-cream": "linear-gradient(180deg, #FFFBF0 0%, #FFFFFF 100%)",
      },
    },
  },
  plugins: [],
};

export default config;
