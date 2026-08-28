/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#2f2926",
        paper: "#f7f2e9",
        moss: "#53645a",
        clay: "#a96852",
      },
      boxShadow: {
        soft: "0 18px 50px rgba(66, 49, 40, 0.12)",
      },
    },
  },
  plugins: [],
};
