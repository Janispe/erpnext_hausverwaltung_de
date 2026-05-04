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

	const orig_link_formatter = frappe.form.formatters.Link;

	frappe.form.formatters.Link = function (value, docfield, options, doc) {
		// Vor dem Original-Formatter: ggfs. ``<fieldname>_name`` aus der Row in
		// den globalen Link-Title-Cache übernehmen. Der Original-Formatter
		// rendert dann den Title als Label, mit Klick-Through zur ID.
		try {
			if (doc && docfield && value) {
				const target = docfield._options || docfield.options;
				const title_key = docfield.fieldname + "_name";
				if (target && doc[title_key] && frappe.utils && frappe.utils.add_link_title) {
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
