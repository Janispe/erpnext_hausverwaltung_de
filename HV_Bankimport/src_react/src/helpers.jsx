// Formatierungs-Helfer, Icons und kleine geteilte Komponenten.
// Portiert aus dem Prototyp (bankimport_v2_src/helpers.jsx) — window-Globals
// durch echte ESM-Exports ersetzt.
import React from "react";

export const fmtEUR = (n) => {
	const v = Number(n) || 0;
	const abs = Math.abs(v);
	const s = abs.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	return (v < 0 ? "−" : "") + s + " €";
};

export const fmtDate = (iso) => {
	if (!iso) return "—";
	const [y, m, d] = String(iso).split(" ")[0].split("-");
	if (!y || !m || !d) return String(iso);
	return `${d}.${m}.${y.slice(2)}`;
};

export const fmtDateTime = (value) => {
	if (!value) return "—";
	const raw = String(value).trim();
	const [date, time = ""] = raw.split(/[ T]/);
	const d = fmtDate(date);
	const hm = time.slice(0, 5);
	return hm ? `${d} ${hm}` : d;
};

export const fmtIban = (iban) =>
	iban ? iban.replace(/\s+/g, "").replace(/(.{4})/g, "$1 ").trim() : "";

// Phase pro Zeile (1..4) — wird normalerweise vom Backend mitgeliefert (row.phase),
// hier als Fallback aus rowStatus abgeleitet.
export const PHASE_OF = {
	"phase1-no-party": 1,
	"phase2-no-bt": 2,
	"phase3-open": 3,
	"phase3-ambiguous": 3,
	"phase3-journal": 3,
	"needs_review": 3,
	"error": 3,
	"done": 4,
};

export const STATUS_PILL = {
	"phase1-no-party": { cls: "phase1", lbl: "Partei fehlt" },
	"phase2-no-bt": { cls: "phase2", lbl: "Bank-Tx fehlt" },
	"phase3-open": { cls: "phase3", lbl: "Beleg zuordnen" },
	"phase3-ambiguous": { cls: "warn", lbl: "Mehrdeutig" },
	"phase3-journal": { cls: "phase3", lbl: "Journal nötig" },
	"needs_review": { cls: "warn", lbl: "Prüfen" },
	"error": { cls: "danger", lbl: "Fehler" },
	"done": { cls: "done", lbl: "Gebucht" },
};

export const rowPhase = (row) => row.phase || PHASE_OF[row.rowStatus] || 3;

export const Icon = ({ name, size = 14 }) => {
	const s = { width: size, height: size, display: "inline-block", verticalAlign: "middle" };
	const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
	const paths = {
		search: <><circle cx="7" cy="7" r="5" {...p} /><path d="M11 11l4 4" {...p} /></>,
		plus: <><path d="M8 3v10M3 8h10" {...p} /></>,
		upload: <><path d="M8 11V3M5 6l3-3 3 3M3 13h10" {...p} /></>,
		chev: <><path d="M5 4l4 4-4 4" {...p} /></>,
		chevDown: <><path d="M4 6l4 4 4-4" {...p} /></>,
		arrowDown: <><path d="M8 3v10M4 9l4 4 4-4" {...p} /></>,
		arrowUp: <><path d="M8 13V3M4 7l4-4 4 4" {...p} /></>,
		check: <><path d="M3 8l3 3 7-7" {...p} /></>,
		x: <><path d="M4 4l8 8M12 4l-8 8" {...p} /></>,
		dots: <><circle cx="4" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="8" r="1" fill="currentColor" stroke="none" /></>,
		refresh: <><path d="M3 8a5 5 0 0 1 8.5-3.5M13 8a5 5 0 0 1-8.5 3.5M11 3v2.5h-2M5 13v-2.5h2" {...p} /></>,
		file: <><path d="M4 2h5l3 3v9H4z" {...p} /><path d="M9 2v3h3" {...p} /></>,
		link: <><path d="M7 9a3 3 0 0 0 4 0l2-2a3 3 0 0 0-4-4l-1 1M9 7a3 3 0 0 0-4 0l-2 2a3 3 0 0 0 4 4l1-1" {...p} /></>,
		split: <><path d="M3 4h4l4 8h4M11 4h4M11 4l-1-1M11 4l-1 1" {...p} /></>,
		filter: <><path d="M2 3h12l-4.5 6V14L6.5 12V9z" {...p} /></>,
		download: <><path d="M8 3v8M5 8l3 3 3-3M3 13h10" {...p} /></>,
		download2: <><path d="M8 2v8M5 7l3 3 3-3M3 13h10" {...p} /></>,
		settings: <><circle cx="8" cy="8" r="2.2" {...p} /><path d="M8 1v2M8 13v2M15 8h-2M3 8H1M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4" {...p} /></>,
		info: <><circle cx="8" cy="8" r="6" {...p} /><path d="M8 7v4M8 5h.01" {...p} /></>,
		bolt: <><path d="M9 1L3 9h4l-1 6 6-8H8z" {...p} /></>,
	};
	return <svg style={s} viewBox="0 0 16 16" aria-hidden="true">{paths[name]}</svg>;
};

export const Pill = ({ kind, children }) => <span className={`pill ${kind}`}>{children}</span>;

export const StatusPill = ({ row }) => {
	const s = STATUS_PILL[row.rowStatus];
	if (!s) return null;
	return <Pill kind={s.cls}>{s.lbl}</Pill>;
};

// Spinner / Inline-Busy-Indikator
export const Spinner = ({ size = 14 }) => (
	<span className="hv-spinner" style={{ width: size, height: size }} aria-label="lädt" />
);
