
import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const rawBase = process.env.FRONT_REACT_BASE ?? "/";
const ensureLeadingSlash = rawBase.startsWith("/") ? rawBase : `/${rawBase}`;
const base =
	ensureLeadingSlash === "/"
		? "/"
		: ensureLeadingSlash.endsWith("/")
			? ensureLeadingSlash
			: `${ensureLeadingSlash}/`;

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
