/**
 * Generischer Helper, der "Prozess starten"-Buttons aus der ProcessRuntimeConfig
 * der hausverwaltung-App auf Quell-Doctype-Forms haengt.
 *
 * Verwendung im jeweiligen Quell-Doctype-JS:
 *   frappe.ui.form.on("Mietvertrag", {
 *     refresh(frm) { hausverwaltung.process_triggers.attach_to_form(frm); }
 *   });
 *
 * Der Server-Endpoint get_triggers_for_source liefert pro Quell-Doctype die
 * sichtbaren/erlaubten Trigger; build_trigger_payload baut die new_doc-Defaults
 * fuer den konkreten Source-Doc.
 */
(function () {
	window.hausverwaltung = window.hausverwaltung || {};

	// Cache-Key = (doctype, name) — pro Form-Instanz einmal laden. Bei Navigation
	// zwischen verschiedenen Docs desselben Doctypes wird neu geholt, da
	// visibility_check pro Source-Doc anders ausfallen kann.
	const trigger_cache = {};

	async function _fetch_triggers(doctype, name) {
		const cache_key = `${doctype}::${name || ""}`;
		if (trigger_cache[cache_key]) return trigger_cache[cache_key];
		const { message } = await frappe.call({
			method: "hausverwaltung.hausverwaltung.processes.triggers.get_triggers_for_source",
			args: { source_doctype: doctype, source_name: name || null },
		});
		trigger_cache[cache_key] = message || [];
		return trigger_cache[cache_key];
	}

	async function attach_to_form(frm) {
		if (!frm || frm.is_new()) return;
		let triggers;
		try {
			triggers = await _fetch_triggers(frm.doctype, frm.doc.name);
		} catch (err) {
			console.error("hausverwaltung.process_triggers: fetch failed", err);
			return;
		}
		for (const t of triggers) {
			frm.add_custom_button(
				__(t.button_label),
				async () => {
					try {
						const { message: payload } = await frappe.call({
							method: "hausverwaltung.hausverwaltung.processes.triggers.build_trigger_payload",
							args: { trigger_id: t.trigger_id, source_name: frm.doc.name },
						});
						frappe.new_doc(t.target_doctype, payload || {});
					} catch (err) {
						console.error("hausverwaltung.process_triggers: build_payload failed", err);
						frappe.show_alert(
							{ message: __("Prozess konnte nicht gestartet werden."), indicator: "red" },
							5
						);
					}
				},
				__(t.button_group || "Workflow")
			);
		}
	}

	window.hausverwaltung.process_triggers = { attach_to_form };
})();
