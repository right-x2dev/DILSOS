/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Pretendard"', '"Noto Sans KR"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        ink: { 50: "#f5f7fa", 100: "#e9edf3", 200: "#cfd7e3", 400: "#8593a8", 600: "#4a5568", 800: "#1f2937", 900: "#111827" },
        tower: { 700: "#0f2a44", 800: "#0b2036", 900: "#07182a" },
        accent: { 500: "#2563eb", 600: "#1d4ed8" },
      },
    },
  },
  plugins: [],
};
