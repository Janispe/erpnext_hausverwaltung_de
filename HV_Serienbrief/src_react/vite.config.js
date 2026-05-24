import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Frappe serves apps/hausverwaltung/hausverwaltung/public/ under /assets/hausverwaltung/.
  // The build is copied to public/serienbrief_editor/, so emitted asset URLs must be
  // prefixed accordingly. Override with HV_BASE=./ for fully standalone hosting.
  base: process.env.HV_BASE || "/assets/hausverwaltung/serienbrief_editor/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        // Stable, predictable filenames for Frappe integration
        entryFileNames: "assets/serienbrief-editor.js",
        chunkFileNames: "assets/serienbrief-editor-[hash].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "assets/serienbrief-editor.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
  server: {
    port: 5173,
    open: true,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
