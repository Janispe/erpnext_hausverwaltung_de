// Baut die Serienbrief-React-Apps (Editor + Browser) je mit ihrem eigenen Base-Pfad
// und kopiert sie nach hausverwaltung/public/serienbrief_<app>/, sodass Frappe sie
// unter /assets/hausverwaltung/serienbrief_<app>/ ausliefert.
//
// Wichtig: Bei der Multi-Entry-Vite-Config muss pro App mit HV_APP=<app> gebaut
// werden, damit die index.html ihre Assets unter dem richtigen Base-Pfad
// (/assets/hausverwaltung/serienbrief_<app>/) referenziert. Ein einzelner
// `vite build` (Default-Base) würde falsche Asset-URLs erzeugen.
//
// Durchlauf wird (noch) nicht deployt.
import { cp, mkdir, rm, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, ".."); // apps/hausverwaltung/HV_Serienbrief/src_react

// app → { html: Eintrags-HTML im dist/, bundle: stabiler (hash-loser) Bundle-Basename }
const APPS = {
	editor: { html: "index.html", bundle: "serienbrief-editor" },
	browser: { html: "browser.html", bundle: "serienbrief-browser" },
};

for (const [app, cfg] of Object.entries(APPS)) {
	console.log(`[copy-to-frappe] build ${app} …`);
	execSync("npx vite build", { cwd: root, stdio: "inherit", env: { ...process.env, HV_APP: app } });

	const distAssets = resolve(root, "dist/assets");
	const target = resolve(root, `../../hausverwaltung/public/serienbrief_${app}`);

	await rm(target, { recursive: true, force: true });
	await mkdir(`${target}/assets`, { recursive: true });
	await cp(distAssets, `${target}/assets`, { recursive: true });

	// Die Host-Page lädt jeweils <app>/index.html — beim Browser ist die Quelle browser.html.
	await cp(resolve(root, `dist/${cfg.html}`), `${target}/index.html`);

	// Cache-Bust: Die Bundle-Dateinamen sind bewusst fix (kein Content-Hash) für die
	// Frappe-Integration. Ohne Versions-Query liefert der Browser-Cache nach einem
	// Rebuild das alte Bundle weiter aus → pro Build ?v=<buildId> anhängen. Die
	// shared Chunks haben Hashes und brauchen keinen Bust.
	const buildId = Date.now();
	const indexPath = `${target}/index.html`;
	const html = await readFile(indexPath, "utf8");
	await writeFile(
		indexPath,
		html.replace(new RegExp(`(${cfg.bundle}\\.(?:js|css))(?=["'?])`, "g"), `$1?v=${buildId}`),
	);

	console.log(`[copy-to-frappe] ${app} -> ${target} (cache-bust v=${buildId})`);
}
