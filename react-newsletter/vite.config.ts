// react-newsletter/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // IMPORTANT: base = "/<nom-du-repo>/"
  base: "/veille-tech/",
});