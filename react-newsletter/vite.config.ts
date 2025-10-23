// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/veille-tech/", // ✅ toujours la même base, même en local
  build: { outDir: "dist" },
});