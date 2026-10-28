import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#030303",
          900: "#080808",
          850: "#0d0d0d",
          800: "#131313",
          700: "#1d1d1d",
          600: "#2a2a2a",
        },
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(255,255,255,0.08), 0 24px 80px rgba(0,0,0,0.55)",
      },
    },
  },
  plugins: [],
};

export default config;
