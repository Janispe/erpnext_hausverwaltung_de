// Universaler Link-Title-Hook für Reports + Listen + Forms.
//
// Frappe rendert Link-Spalten standardmäßig als Doc-ID (z.B. "G | VH | 3.OG
// links Mieter: Hilbert, Bieler"). Es nutzt aber einen globalen Cache
// ``frappe._link_titles[<doctype>::<name>]`` falls ein Title-Wert vorliegt —
// dann wird stattdessen der Title als Label gerendert (Click geht weiter zur ID).
//
// Frappe füllt den Cache automatisch in Forms/Listen, aber NICHT in Query-/
// Script-Reports. Dieser Hook schließt die Lücke: vor jedem Link-Cell-Render
// wird gecheckt, ob die Row ein Begleitfeld ``<fieldname>_name`` enthält
// (Konvention die unser Backend-Helper ``enrich_link_titles`` liefert) — wenn
// ja, wird der Wert in den globalen Cache injiziert. Der nachfolgende
// Original-Formatter pickt den Title dann auf und nutzt ihn als Label.
//
// Damit funktioniert die saubere Anzeige automatisch in JEDEM Report der
// ``enrich_link_titles`` aufruft, ohne pro Report Custom-Code zu brauchen.

(function () {
	if (window.__hv_link_title_hook_installed) return;
	if (!frappe || !frappe.form || !frappe.form.formatters || !frappe.form.formatters.Link) return;
	window.__hv_link_title_hook_installed = true;

	// Transaktionale Doctypes: hier ist die Doc-ID (z.B. ACC-SINV-…) der
	// semantisch wichtige Identifier. Frappe-/ERPNext-seitig ist der
	// title_field oft eine historische Customer-Name-Kopie, die im Bestand
	// abweichen kann (= verwirrend). Für diese Doctypes unterdrücken wir
	// die Title-Anzeige aktiv: alles was Frappe/das Backend in den Cache
	// geschrieben hat, wird vor dem Render rausgelöscht, sodass die ID als
	// Label gerendert wird.
	const NO_TITLE_DOCTYPES = new Set([
		"Sales Invoice",
		"Purchase Invoice",
		"Payment Entry",
		"Journal Entry",
		"Delivery Note",
		"Sales Order",
		"Purchase Order",
		"Purchase Receipt",
		"Stock Entry",
		"Quotation",
		"Material Request",
		"Dunning",
	]);

	const orig_link_formatter = frappe.form.formatters.Link;

	frappe.form.formatters.Link = function (value, docfield, options, doc) {
		try {
			const target = docfield && (docfield._options || docfield.options);

			if (target && NO_TITLE_DOCTYPES.has(target)) {
				// Cached Title für transaktionale Doctypes wegnehmen,
				// damit der Original-Formatter die ID als Label rendert.
				if (frappe._link_titles && value) {
					delete frappe._link_titles[target + "::" + value];
				}
			} else if (doc && docfield && value && target) {
				// Nicht-transaktional: ``<fieldname>_name`` aus der Row in
				// den Cache übernehmen. Der Original-Formatter zeigt dann
				// den Title als Label, Klick öffnet die ID.
				const title_key = docfield.fieldname + "_name";
				if (doc[title_key] && frappe.utils && frappe.utils.add_link_title) {
					frappe.utils.add_link_title(target, value, doc[title_key]);
				}
			}
		} catch (e) {
			// Defensiv: Hook darf das Rendering nie crashen lassen
			console.warn("hv link_title_hook:", e);
		}
		return orig_link_formatter.call(this, value, docfield, options, doc);
	};
})();
