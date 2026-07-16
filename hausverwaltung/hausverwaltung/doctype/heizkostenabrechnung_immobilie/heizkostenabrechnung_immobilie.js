// Form-Skript für „Heizkostenabrechnung Immobilie".
//
// Buttons:
// - Im Entwurf: „Mieter-Drafts erzeugen" → ruft create_mieter_drafts; Tabelle
//   wird beim Reload aus den frischen Mieter-Docs hydriert.
//
// Tabellen-Verhalten:
// - `customer`, `wohnung`, `mietvertrag` sind read-only.
// - `kosten_gesamt` und `vorauszahlungen` sind immer editierbar — auch bei
//   submitteten Parents/Children.
//   Bei submitteten Parents triggert ein Save automatisch die Diff-only
//   Korrektur: für geänderte Werte werden alte SIs storniert und neue erstellt.
// - `differenz` wird bei jeder Betragsänderung live neu berechnet.

frappe.ui.form.on("Heizkostenabrechnung Immobilie", {
	setup(frm) {
		// Frappe darf die Mieter-Abrechnungen nicht über seinen generischen
		// "Alle verknüpften Dokumente abbrechen"-Dialog stornieren. Der Parent
		// übernimmt die Kaskade selbst, setzt dabei die internen Flags und prüft
		// vorher atomar auf bereits zugeordnete Zahlungen.
		frm.ignore_doctypes_on_cancel_all = ["Heizkostenabrechnung Mieter"];
	},

	onload(frm) {
		_prepare_amendment(frm);
	},

	refresh(frm) {
		_add_buttons(frm);
		_show_correction_banner(frm);
		_ensure_amendment_drafts(frm);
	},
});

function _prepare_amendment(frm) {
	if (!frm.is_new() || !frm.doc.amended_from || frm.__hk_amendment_prepared) return;

	// Der Standard-Amend kopiert die Links auf die inzwischen aufgehobenen
	// Mieter-Abrechnungen. Sie werden serverseitig ebenfalls entfernt; das
	// sofortige Leeren verhindert aber schon im Browser eine irreführende Tabelle.
	frm.__hk_amendment_prepared = true;
	frm.clear_table("mieter_positionen");
	frm.doc.status = "Eingang";
	frm.refresh_fields(["mieter_positionen", "status"]);
	frappe.show_alert(
		{
			message: __("Neuer Änderungsentwurf: Beim Speichern werden automatisch neue Mieter-Drafts mit den bisherigen Beträgen erzeugt."),
			indicator: "blue",
		},
		10,
	);
}

function _ensure_amendment_drafts(frm) {
	if (
		frm.is_new() ||
		frm.doc.docstatus !== 0 ||
		!frm.doc.amended_from ||
		(frm.doc.mieter_positionen || []).length ||
		frm.__hk_ensuring_amendment_drafts
	) return;

	// Repariert auch einen bereits mit der früheren Logik gespeicherten,
	// leeren Amend-Entwurf. Die API ist idempotent und legt nur fehlende Drafts an.
	frm.__hk_ensuring_amendment_drafts = true;
	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.create_mieter_drafts",
		args: { name: frm.doc.name },
		freeze: true,
		freeze_message: __("Neue Mieter-Abrechnungen werden aus dem stornierten Stand erzeugt…"),
		callback(r) {
			const m = r && r.message;
			if (!m || (!m.created.length && !m.skipped.length)) return;
			frm.reload_doc();
		},
	});
}

frappe.ui.form.on("Heizkostenabrechnung Position", {
	kosten_gesamt(frm, cdt, cdn) {
		_recompute_row_difference(frm, cdt, cdn);
	},

	vorauszahlungen(frm, cdt, cdn) {
		_recompute_row_difference(frm, cdt, cdn);
		frappe.show_alert(
			{
				message: __("Vorauszahlung manuell angepasst. Die gebuchten Zahlungen bleiben unverändert; geändert wird nur diese HK-Abrechnung."),
				indicator: "orange",
			},
			7,
		);
	},
});

function _recompute_row_difference(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;
	const vor = parseFloat(row.vorauszahlungen || 0);
	const kos = parseFloat(row.kosten_gesamt || 0);
	row.differenz = Math.round((kos - vor) * 100) / 100;
	frm.refresh_field("mieter_positionen");
}

function _add_buttons(frm) {
	if (frm.is_new()) return;

	if (frm.doc.docstatus === 0) {
		frm.add_custom_button(
			__("Mieter-Drafts erzeugen"),
			() => _create_drafts(frm),
			__("Aktionen"),
		);
	}
}

function _show_correction_banner(frm) {
	// Auf submitteten Parents zeigt ein Hinweis-Banner, dass Werte-Korrekturen
	// in der Tabelle automatisch alte Sales Invoices stornieren + neue erstellen.
	if (frm.is_new() || frm.doc.docstatus !== 1) return;
	frm.dashboard.set_headline_alert(
		`<div>${__("Diese Abrechnung ist submittet. Du kannst <strong>Kosten gesamt</strong> und <strong>Vorauszahlung</strong> weiter bearbeiten — beim Speichern werden für geänderte Werte die alten Ausgleichsbelege storniert und korrekt neu erstellt. Die ursprünglichen Vorauszahlungsbuchungen bleiben unverändert.")}</div>`,
		"blue",
	);
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
