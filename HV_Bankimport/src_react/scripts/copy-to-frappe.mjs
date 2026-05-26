// Baut die Bankimport-React-App und kopiert sie nach
// hausverwaltung/public/bankimport_v2/, sodass Frappe sie unter
// /assets/hausverwaltung/bankimport_v2/ ausliefert. Die Host-Page
// (hausverwaltung/page/bankimport_v2) lädt index.html in ein <iframe>.
//
// Analog zu HV_Serienbrief/src_react/scripts/copy-to-frappe.mjs, aber Single-App.
import { cp, mkdir, rm, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, ".."); // apps/hausverwaltung/HV_Bankimport/src_react

const BUNDLE = "bankimport"; // stabiler (hash-loser) Bundle-Basename

console.log("[copy-to-frappe] build bankimport …");
execSync("npx vite build", { cwd: root, stdio: "inherit" });

const distAssets = resolve(root, "dist/assets");
const target = resolve(root, "../../hausverwaltung/public/bankimport_v2");

await rm(target, { recursive: true, force: true });
await mkdir(`${target}/assets`, { recursive: true });
await cp(distAssets, `${target}/assets`, { recursive: true });
await cp(resolve(root, "dist/index.html"), `${target}/index.html`);

// Cache-Bust: Die Bundle-Dateinamen sind bewusst fix (kein Content-Hash) für die
// Frappe-Integration. Ohne Versions-Query liefert der Browser-Cache nach einem
// Rebuild das alte Bundle weiter aus → pro Build ?v=<buildId> anhängen.
const buildId = Date.now();
const indexPath = `${target}/index.html`;
const html = await readFile(indexPath, "utf8");
await writeFile(
	indexPath,
	html.replace(new RegExp(`(${BUNDLE}\\.(?:js|css))(?=["'?])`, "g"), `$1?v=${buildId}`),
);

console.log(`[copy-to-frappe] bankimport -> ${target} (cache-bust v=${buildId})`);
