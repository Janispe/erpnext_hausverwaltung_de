// Form-Skript für „Heizkostenabrechnung Immobilie".
//
// Buttons:
// - Im Entwurf: „Mieter-Drafts erzeugen" → ruft create_mieter_drafts; Tabelle
//   wird beim Reload aus den frischen Mieter-Docs hydriert.
// - Im Entwurf: „Alle Mieter submitten" → submittet einzeln (Debug/Wenn HV
//   nicht den Parent komplett submitten will).
//
// Tabellen-Verhalten:
// - `vorauszahlungen`, `customer`, `wohnung`, `mietvertrag` sind read-only
//   (kommen aus den Mietrechnungen / Mietvertrag-Stammdaten).
// - `kosten_gesamt` ist editierbar — aber nur wenn `child_docstatus = 0`
//   (also der zugehörige HK Mieter Doc noch im Entwurf). Bei submitteten
//   Children ist die Row gelockt.
// - `differenz` wird live mitberechnet bei Edit von `kosten_gesamt`.

frappe.ui.form.on("Heizkostenabrechnung Immobilie", {
	refresh(frm) {
		_add_buttons(frm);
		_lock_submitted_rows(frm);
	},
	mieter_positionen_on_form_rendered(frm) {
		_lock_submitted_rows(frm);
	},
});

frappe.ui.form.on("Heizkostenabrechnung Position", {
	kosten_gesamt(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row) return;
		const vor = parseFloat(row.vorauszahlungen || 0);
		const kos = parseFloat(row.kosten_gesamt || 0);
		row.differenz = Math.round((kos - vor) * 100) / 100;
		frm.refresh_field("mieter_positionen");
	},
});

function _add_buttons(frm) {
	if (frm.is_new()) return;

	if (frm.doc.docstatus === 0) {
		const has_drafts = (frm.doc.mieter_positionen || []).some(
			(r) => (r.child_docstatus || 0) === 0 && r.heizkostenabrechnung_mieter,
		);
		const has_unsynced = (frm.doc.mieter_positionen || []).length === 0;

		frm.add_custom_button(
			__("Mieter-Drafts erzeugen"),
			() => _create_drafts(frm),
			__("Aktionen"),
		);

		if (has_drafts) {
			frm.add_custom_button(
				__("Alle Mieter einzeln submitten"),
				() => _submit_all(frm),
				__("Aktionen"),
			);
		}
	}
}

function _lock_submitted_rows(frm) {
	// Frappe-Grid: pro Row prüfen ob child_docstatus !== 0; wenn submittet → Felder
	// auf read-only stellen via grid.get_field per Row-Index.
	const grid = frm.fields_dict.mieter_positionen?.grid;
	if (!grid) return;
	(frm.doc.mieter_positionen || []).forEach((row, idx) => {
		const docstatus = parseInt(row.child_docstatus || 0);
		if (docstatus !== 0) {
			// Submitted oder Cancelled → kosten_gesamt sperren
			const editable = grid.is_editable;
			const grid_row = grid.grid_rows?.[idx];
			if (grid_row && grid_row.docfields) {
				grid_row.docfields.forEach((df) => {
					if (df.fieldname === "kosten_gesamt") {
						df.read_only = 1;
					}
				});
				grid_row.refresh();
			}
		}
	});
}

function _create_drafts(frm) {
	frappe.confirm(
		__("Für jeden im Zeitraum aktiven Mietvertrag der Immobilie wird ein HK-Mieter-Draft mit vorbefüllter Vorauszahlung angelegt. Fortfahren?"),
		() => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.create_mieter_drafts",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __("Mieter-Drafts werden erzeugt…"),
				callback(r) {
					if (!r || !r.message) return;
					const m = r.message;
					const lines = [
						__("Neu angelegt: {0}", [m.created.length]),
						__("Übersprungen (existiert bereits): {0}", [m.skipped.length]),
					];
					if (m.no_wohnung && m.no_wohnung.length) {
						lines.push(__("Ohne Customer/Wohnung: {0}", [m.no_wohnung.length]));
					}
					frappe.msgprint({
						title: __("Ergebnis"),
						message: lines.join("<br>") +
							(m.created.length
								? "<br><br>" + __("Tabelle unten wurde aktualisiert. Bitte Kosten gesamt pro Mieter eintragen, dann Save + Submit.")
								: ""),
						indicator: m.created.length ? "green" : "blue",
					});
					frm.reload_doc();
				},
			});
		},
	);
}

function _submit_all(frm) {
	frappe.confirm(
		__("Alle Mieter-Drafts mit gesetztem kosten_gesamt werden einzeln submittet (erzeugt Sales Invoices). Beim Parent-Submit passiert das ohnehin automatisch — diese Aktion ist nur für Debug/Teil-Submits gedacht. Fortfahren?"),
		() => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.submit_all_pending",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __("Submitting…"),
				callback(r) {
					if (!r || !r.message) return;
					const m = r.message;
					const lines = [__("Submittet: {0}", [m.submitted.length])];
					if (m.skipped.length) {
						lines.push(
							__("Übersprungen: {0}", [m.skipped.length]) +
								"<br>" +
								m.skipped
									.map((s) => `&nbsp;&nbsp;${s.name}: ${s.reason}`)
									.join("<br>"),
						);
					}
					if (m.errors.length) {
						lines.push(
							__("Fehler: {0}", [m.errors.length]) +
								"<br>" +
								m.errors
									.map((e) => `&nbsp;&nbsp;${e.name}: ${e.error}`)
									.join("<br>"),
						);
					}
					frappe.msgprint({
						title: __("Ergebnis"),
						message: lines.join("<br>"),
						indicator: m.errors.length ? "red" : m.submitted.length ? "green" : "blue",
					});
					frm.reload_doc();
				},
			});
		},
	);
}
