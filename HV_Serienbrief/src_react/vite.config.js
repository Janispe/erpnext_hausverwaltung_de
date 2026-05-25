import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Multi-entry build: editor + browser + durchlauf.
// Frappe serves apps/hausverwaltung/hausverwaltung/public/ under /assets/hausverwaltung/.
// Each app builds to its own folder under public/, served independently to a Frappe Page iframe.
//
// Output structure (in dist/):
//   index.html              → Editor entry HTML
//   browser.html            → Browser entry HTML
//   durchlauf.html          → Durchlauf entry HTML
//   assets/
//     serienbrief-editor.js + .css
//     serienbrief-browser.js + .css
//     serienbrief-durchlauf.js + .css
//     shared chunks (e.g. react vendor, icons)
//
// Each app gets a stable, predictable bundle name; chunks get hashed names.
// The Frappe page iframe loads its app's HTML directly.
//
// Override the base path with HV_APP=<editor|browser|durchlauf> + HV_BASE=./ for
// fully standalone hosting; otherwise the assets are prefixed for Frappe.

const APP_BASES = {
  editor:    "/assets/hausverwaltung/serienbrief_editor/",
  browser:   "/assets/hausverwaltung/serienbrief_browser/",
  durchlauf: "/assets/hausverwaltung/serienbrief_durchlauf/",
};

// When building a single app (HV_APP=editor), use that app's base path.
// When building all (default), use a neutral root that works for all three.
const singleApp = process.env.HV_APP;
const base = process.env.HV_BASE || (singleApp ? APP_BASES[singleApp] : "/assets/hausverwaltung/");

export default defineConfig({
  plugins: [react()],
  base,
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      // Beim Frappe-Deploy wird pro App mit HV_APP=<app> gebaut. Dann nur DIESE eine
      // Entry als Input → ein einziges, in sich geschlossenes Bundle (kein geteilter
      // chunk-*.js), genau wie der ursprüngliche Editor-Build. Das vermeidet fragile
      // Shared-Chunk-Dateien im ausgelieferten /assets/.../serienbrief_<app>/-Ordner.
      // Ohne HV_APP (lokaler Dev) bleiben alle drei Entries.
      input: singleApp
        ? { [singleApp]: resolve(__dirname, singleApp === "editor" ? "index.html" : `${singleApp}.html`) }
        : {
            editor:    resolve(__dirname, "index.html"),
            browser:   resolve(__dirname, "browser.html"),
            durchlauf: resolve(__dirname, "durchlauf.html"),
          },
      output: {
        // Map each entry to a stable bundle name; chunks/assets remain hashed for cache-busting
        entryFileNames: (chunk) => {
          if (chunk.name === "editor")    return "assets/serienbrief-editor.js";
          if (chunk.name === "browser")   return "assets/serienbrief-browser.js";
          if (chunk.name === "durchlauf") return "assets/serienbrief-durchlauf.js";
          return "assets/[name]-[hash].js";
        },
        chunkFileNames: "assets/chunk-[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          // CSS files coming from each entry's main.jsx → stable per-app name
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            // Vite names the CSS file after the entry chunk that produced it
            if (assetInfo.name.startsWith("editor"))    return "assets/serienbrief-editor.css";
            if (assetInfo.name.startsWith("browser"))   return "assets/serienbrief-browser.css";
            if (assetInfo.name.startsWith("durchlauf")) return "assets/serienbrief-durchlauf.css";
            return "assets/[name]-[hash].css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
  server: {
    port: 5173,
    open: "/",
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
