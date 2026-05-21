// Dekoriert echtes Vorlagen-HTML für die read-only-Anzeige im Editor:
// Jinja-Tokens werden in farbige Chips / Marker verwandelt, damit echte Vorlagen
// optisch zur Design-Sprache des Editors passen.
//
// Das HTML stammt aus den eigenen `Serienbrief Vorlage`-Records (admin-authored)
// und wird ohnehin schon im Frappe-Formular via Rich-Text gerendert — wir fügen
// nur Darstellungs-Spans um die `{{ }}` / `{% %}`-Tokens herum ein.

const PREFIX_GROUP = {
	mieter: "mieter",
	hauptmieter: "mieter",
	verwalter: "verwalter",
	wohnung: "wohnung",
	immobilie: "wohnung",
	mietvertrag: "vertrag",
	saldo: "vertrag",
	saldo_betrag: "vertrag",
	kaltmiete: "vertrag",
	nebenkosten: "vertrag",
	warmmiete: "vertrag",
	mahnstufe: "vertrag",
	datum: "datum",
	datum_iso: "datum",
	stichtag: "datum",
	frist_tage: "datum",
	bankkonto: "bank",
};

function escapeHtml(s) {
	return String(s)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;");
}

function groupForToken(inner) {
	const prefix = (inner || "").trim().split(/[.\s(]/)[0].toLowerCase();
	return PREFIX_GROUP[prefix] || "mieter";
}

export function decorateTemplateHtml(html) {
	if (!html) return "";
	let out = html;

	// 1) Baustein-Aufrufe: {{ baustein("Name") }} → eigener Baustein-Chip
	out = out.replace(
		/\{\{\s*baustein\(\s*["']([^"']+)["']\s*\)\s*\}\}/g,
		(_m, name) => `<span class="chip" data-group="baustein">⧉&nbsp;${escapeHtml(name)}</span>`
	);

	// 2) Generische Platzhalter: {{ ... }} → farbiger Chip nach Präfix
	out = out.replace(/\{\{([^}]+)\}\}/g, (m, inner) => {
		const group = groupForToken(inner);
		return `<span class="chip" data-group="${group}">${escapeHtml(m.trim())}</span>`;
	});

	// 3) Logik-Tags: {% if ... %} / {% endif %} → dezenter Jinja-Marker
	out = out.replace(
		/\{%([^%]*)%\}/g,
		(m) => `<span class="jinja-token">${escapeHtml(m.trim())}</span>`
	);

	return out;
}
