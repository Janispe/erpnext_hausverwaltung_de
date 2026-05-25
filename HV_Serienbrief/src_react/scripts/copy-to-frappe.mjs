// Kopiert den Vite-Build nach hausverwaltung/public/serienbrief_editor/, sodass
// Frappe ihn unter /assets/hausverwaltung/serienbrief_editor/ ausliefert.
// Ersetzt den manuellen `cp`-Schritt aus der README (Copy-Falle).
import { cp, mkdir, rm, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// here = apps/hausverwaltung/HV_Serienbrief/src_react/scripts
// Ziel = apps/hausverwaltung/hausverwaltung/public/serienbrief_editor (3x hoch zu apps/hausverwaltung)
const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "../dist");
const target = resolve(here, "../../../hausverwaltung/public/serienbrief_editor");

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(`${dist}/assets`, `${target}/assets`, { recursive: true });
await cp(`${dist}/index.html`, `${target}/index.html`);

// Cache-Bust: Die Bundle-Dateinamen sind bewusst fix (serienbrief-editor.js/.css)
// für die Frappe-Integration, haben also KEINEN Content-Hash. Ohne Versions-Query
// liefert der Browser-HTTP-Cache nach einem Rebuild das alte Bundle weiter aus
// (die Host-Page cache-bustet nur die index.html, nicht die darin referenzierten
// Assets). Daher pro Build eine ?v=<buildId> an die JS-/CSS-URLs anhängen.
const buildId = Date.now();
const indexPath = `${target}/index.html`;
const html = await readFile(indexPath, "utf8");
await writeFile(
	indexPath,
	html.replace(/(serienbrief-editor\.(?:js|css))(?=["'?])/g, `$1?v=${buildId}`),
);

console.log(`[copy-to-frappe] ${dist} -> ${target} (cache-bust v=${buildId})`);
