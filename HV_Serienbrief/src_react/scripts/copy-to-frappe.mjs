// Kopiert den Vite-Build nach hausverwaltung/public/serienbrief_editor/, sodass
// Frappe ihn unter /assets/hausverwaltung/serienbrief_editor/ ausliefert.
// Ersetzt den manuellen `cp`-Schritt aus der README (Copy-Falle).
import { cp, mkdir, rm } from "node:fs/promises";
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

console.log(`[copy-to-frappe] ${dist} -> ${target}`);
