import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Single-app build für die Bankimport-React-UI.
// Frappe liefert apps/hausverwaltung/hausverwaltung/public/ unter
// /assets/hausverwaltung/ aus; der Build landet in public/bankimport_v2/ und
// wird von der Frappe-Page (hausverwaltung/page/bankimport_v2) per <iframe>
// eingebettet — exakt das Serienbrief-Muster (Style-/Layout-Isolation, weil
// das CSS globale body/100vh-Selektoren nutzt).
//
// Override für vollständig standalone-Hosting: HV_BASE=./ vite build.

const base = process.env.HV_BASE || "/assets/hausverwaltung/bankimport_v2/";

export default defineConfig({
  plugins: [react()],
  base,
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        // Stabiler, hash-loser Bundle-Name für die Frappe-Integration; der
        // Cache-Bust passiert über ?v=<buildId> in der ausgelieferten index.html
        // (siehe scripts/copy-to-frappe.mjs).
        entryFileNames: "assets/bankimport.js",
        chunkFileNames: "assets/chunk-[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "assets/bankimport.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
  server: {
    port: 5174,
    open: "/",
  },
});
