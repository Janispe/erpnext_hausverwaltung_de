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

	async before_submit(frm) {
		const response = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.get_duplicate_heads",
			args: { name: frm.doc.name, von: frm.doc.von, bis: frm.doc.bis },
		});
		if ((response.message || []).length) {
			frappe.validated = false;
			frappe.msgprint({
				title: __("Doppelte Heizkostenabrechnung verhindert"),
				message: __("Für diesen Zeitraum ist bereits eine Heizkostenabrechnung eingereicht: {0}. Bitte diese Abrechnung berichtigen. Administratoren können dort über „Korrekturentwurf erstellen“ zuerst ein kontrolliertes Sammelstorno ausführen.", [frappe.utils.escape_html(response.message.join(", "))]),
				indicator: "orange",
			});
			return;
		}
		if (!(frm.doc.mieter_positionen || []).some((row) => Number(row.kosten_gesamt || 0) === 0)) return;
		await new Promise((resolve) => {
			frappe.confirm(
				__("Die erfassten Heizkosten betragen null Euro. Dadurch werden die Vorauszahlungen vollständig gutgeschrieben. Möchten Sie die Abrechnung wirklich einreichen?"),
				async () => { await frm.set_value("nullkosten_bestaetigt", 1); resolve(); },
				() => { frappe.validated = false; resolve(); },
			);
		});
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
	if (frm.doc.docstatus === 1 && frappe.user_roles.includes("System Manager")) {
		frm.add_custom_button(__("Korrekturentwurf erstellen"), () => _create_correction_draft(frm));
	}

	if (frm.doc.docstatus === 0) {
		if (!frm.doc.ruecklauf_import && frm.perm[0]?.write) {
			frm.add_custom_button(__("Rücklauf importieren"), () => _open_hk_return(frm), __("Aktionen"));
		}
		frm.add_custom_button(
			__("Mieter-Drafts erzeugen"),
			() => _create_drafts(frm),
			__("Aktionen"),
		);
	}
}

function _create_correction_draft(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Bitte Änderungen zuerst speichern, bevor du einen Korrekturentwurf erstellst."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Heizkostenabrechnung kontrolliert berichtigen"),
		fields: [
			{ fieldtype: "HTML", options: __("Die bisherige Abrechnung und ihre Ausgleichsbelege werden zuerst storniert. Bereits zugeordnete Zahlungen verhindern das Sammelstorno. Anschließend entsteht ein verknüpfter Änderungsentwurf mit den bisherigen Beträgen. Prüfe und korrigiere diesen Entwurf vor dem erneuten Einreichen.") },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Begründung der Korrektur"), reqd: 1 },
		],
		primary_action_label: __("Stornieren und Entwurf erstellen"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.create_correction_draft",
				args: { name: frm.doc.name, reason: values.reason, confirmed: 1 },
				freeze: true,
				freeze_message: __("Abrechnung wird storniert und Änderungsentwurf erstellt…"),
				callback(r) {
					if (!r.message?.name) return;
					dialog.hide();
					frappe.set_route("Form", "Heizkostenabrechnung Immobilie", r.message.name);
				},
			}).always(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
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

const hk_return_api = "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.ruecklauf";

function _open_hk_return(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Bitte die Heizkostenabrechnung zuerst speichern."));
		return;
	}
	const setup = new frappe.ui.Dialog({
		title: __("Messdienst-Rücklauf importieren"),
		fields: [
			{ fieldname: "liegenschaft", fieldtype: "Data", label: __("Messdienst-Liegenschaft aus der Abrechnung"), reqd: 1 },
			{ fieldname: "kontrollsumme", fieldtype: "Data", label: __("Bruttokontrollsumme Heizung und Warmwasser inkl. Leerstand (EUR)"), reqd: 1 },
			{ fieldname: "kontrollbeleg", fieldtype: "Data", label: __("Quelle der Kontrollsumme in der Abrechnung"), reqd: 1 },
		],
		primary_action_label: __("Private D-Datei auswählen"),
		primary_action(values) {
			new frappe.ui.FileUploader({
				doctype: frm.doctype,
				docname: frm.docname,
				make_attachments_public: false,
				allow_toggle_private: false,
				allow_web_link: false,
				allow_google_drive: false,
				allow_take_photo: false,
				disable_file_browser: true,
				allow_multiple: false,
				restrictions: { allowed_file_types: [".dat"], max_file_size: 5 * 1024 * 1024 },
				on_success(file) {
					setup.hide();
					_show_hk_return(frm, { name: frm.docname, datei: file.name, ...values });
				},
			});
		},
	});
	setup.show();
}

async function _show_hk_return(frm, args) {
	const zuordnungen = {};
	const dialog = new frappe.ui.Dialog({
		title: __("Messdienst-Rücklauf prüfen"),
		size: "extra-large",
		fields: [{ fieldname: "vorschau", fieldtype: "HTML" }],
	});
	const content = dialog.fields_dict.vorschau.$wrapper;
	const primary = dialog.get_primary_btn();
	const call = async (action, extra = {}) => (await frappe.call({
		method: `${hk_return_api}.${action}`,
		args: { ...args, zuordnungen, ...extra },
		freeze: true,
	})).message;
	const refresh = async () => {
		primary.hide();
		const data = await call("vorschau");
		content.empty();
		const amounts = __("Summe {0} EUR · davon Leerstand {1} EUR · Kontrollsumme {2} EUR", [
			data.summe, data.leerstand_summe, data.kontrollsumme,
		]);
		$("<p>").text(amounts).appendTo(content);
		for (const error of data.fehler) $("<p>").addClass("text-danger").text(error).appendTo(content);
		const table = $("<table>").addClass("table table-sm").appendTo($("<div>").addClass("table-responsive").appendTo(content));
		const heading = $("<tr>").appendTo($("<thead>").appendTo(table));
		for (const label of ["Zeile", "Kennung", "Messdienstwohnung", "Von", "Bis", "EUR", "Zuordnung", ""]) {
			$("<th>").text(__(label)).appendTo(heading);
		}
		const body = $("<tbody>").appendTo(table);
		for (const row of data.zeilen) {
			const tr = $("<tr>").appendTo(body);
			const target = row.grund || (row.typ === "Leerstand" ? __("Leerstand · {0}", [row.wohnung]) : row.mietvertrag);
			for (const value of [row.zeile, row.kennung, row.messdienst_wohnung, row.von, row.bis, row.betrag, target]) {
				$("<td>").text(value ?? "–").appendTo(tr);
			}
			const actions = $("<td>").appendTo(tr);
			if (row.automatisch && !row.manuell) continue;
			$("<button type='button' class='btn btn-default btn-xs'>").text(__("Zuordnen")).appendTo(actions)
				.on("click", () => _assign_hk_return_row(row, frm, async (mapping) => {
					if (mapping) zuordnungen[row.zeile] = mapping;
					else delete zuordnungen[row.zeile];
					await refresh();
				}));
		}
		if (data.fehler.length) return;
		dialog.set_primary_action(__("Freigeben und in Entwürfe übernehmen"), async () => {
			dialog.disable_primary_action();
			try {
				await call("uebernehmen", { freigabe_id: data.freigabe_id });
				dialog.hide();
				await frm.reload_doc();
				frappe.show_alert({ message: __("Rücklauf in die Mieterentwürfe übernommen"), indicator: "green" });
			} finally {
				dialog.enable_primary_action();
			}
		});
		primary.show();
	};
	await refresh();
	dialog.show();
}

function _assign_hk_return_row(row, frm, apply) {
	const dialog = new frappe.ui.Dialog({
		title: __("Zeile {0} zuordnen", [row.zeile]),
		fields: [
			{ fieldname: "typ", fieldtype: "Select", options: ["Automatisch", "Mietvertrag", "Leerstand"], label: __("Zuordnung"), default: row.manuell && row.typ ? row.typ : "Mietvertrag", reqd: 1 },
			{ fieldname: "mietvertrag", fieldtype: "Link", options: "Mietvertrag", label: __("Mietvertrag"), default: row.mietvertrag,
				depends_on: "eval:doc.typ === 'Mietvertrag'", mandatory_depends_on: "eval:doc.typ === 'Mietvertrag'" },
			{ fieldname: "leerstand", fieldtype: "Link", options: "Wohnung", label: __("Leerstehende Wohnung"),
				default: row.typ === "Leerstand" ? row.wohnung : undefined,
				depends_on: "eval:doc.typ === 'Leerstand'", mandatory_depends_on: "eval:doc.typ === 'Leerstand'",
				get_query: () => ({ filters: { immobilie: frm.doc.immobilie } }) },
		],
		primary_action_label: __("Vorschau aktualisieren"),
		async primary_action(values) {
			const mapping = values.typ === "Leerstand" ? { leerstand: values.leerstand } :
				values.typ === "Mietvertrag" ? { mietvertrag: values.mietvertrag } : null;
			dialog.hide();
			await apply(mapping);
		},
	});
	dialog.show();
}
