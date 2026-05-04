// Form-Skript für „Heizkostenabrechnung Mieter".
//
// Verantwortlichkeiten:
// - Bei Mietvertrag-/Zeitraum-Änderung: Vorauszahlungs-Vorschlag (IST + SOLL)
//   via whitelisted Python-Helper holen und anzeigen.
// - Wenn `vorauszahlungen` noch leer/0 ist: mit IST-Wert vorbefüllen.
// - Wenn der HV `vorauszahlungen` manuell überschreibt: Hinweis-Toast zeigen.
// - Differenz-Indicator (rot = Nachzahlung, grün = Guthaben) im Header.

frappe.ui.form.on("Heizkostenabrechnung Mieter", {
	refresh(frm) {
		_show_diff_indicator(frm);
	},

	mietvertrag(frm) {
		_refresh_vorauszahlung_vorschlag(frm);
	},

	von(frm) {
		_refresh_vorauszahlung_vorschlag(frm);
	},

	bis(frm) {
		_refresh_vorauszahlung_vorschlag(frm);
	},

	vorauszahlungen(frm) {
		_show_diff_indicator(frm);
		_warn_if_overridden(frm);
	},

	kosten_gesamt(frm) {
		_show_diff_indicator(frm);
	},
});

function _refresh_vorauszahlung_vorschlag(frm) {
	if (frm.doc.docstatus !== 0) return; // nur im Entwurf
	if (!frm.doc.mietvertrag || !frm.doc.von || !frm.doc.bis) return;

	frappe.call({
		method:
			"hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_mieter.heizkostenabrechnung_mieter.get_vorauszahlung_vorschlag",
		args: {
			mietvertrag: frm.doc.mietvertrag,
			von: frm.doc.von,
			bis: frm.doc.bis,
		},
		callback(r) {
			if (!r || !r.message) return;
			const ist = r.message.ist || 0;
			const soll = r.message.soll || 0;

			frm.set_df_property("vorauszahlungen_ist", "description",
				__("Tatsächlich gezahlt im Zeitraum: ") + format_currency(ist, "EUR"));
			frm.set_df_property("vorauszahlungen_soll", "description",
				__("Laut Mietrechnung erwartet: ") + format_currency(soll, "EUR"));

			// Virtuelle Felder im Formular sichtbar setzen (sind read_only)
			frm.set_value("vorauszahlungen_ist", ist);
			frm.set_value("vorauszahlungen_soll", soll);

			// Vorbefüllen wenn vorauszahlungen noch leer/0
			if (!frm.doc.vorauszahlungen) {
				frm.set_value("vorauszahlungen", ist);
			}
			_show_diff_indicator(frm);
		},
	});
}

function _show_diff_indicator(frm) {
	const kosten = parseFloat(frm.doc.kosten_gesamt || 0);
	const vor = parseFloat(frm.doc.vorauszahlungen || 0);
	const diff = Math.round((kosten - vor) * 100) / 100;
	if (Math.abs(diff) < 0.01) {
		frm.dashboard.clear_headline();
		frm.dashboard.set_headline_alert(
			`<div>${__("Ausgeglichen — kein Ausgleichsbeleg nötig.")}</div>`,
			"green",
		);
		return;
	}
	if (diff > 0) {
		frm.dashboard.set_headline_alert(
			`<div>${__("Nachzahlung")}: <strong>${format_currency(diff, "EUR")}</strong> ${__("(wird beim Submit als Sales Invoice erzeugt)")}</div>`,
			"orange",
		);
	} else {
		frm.dashboard.set_headline_alert(
			`<div>${__("Guthaben")}: <strong>${format_currency(Math.abs(diff), "EUR")}</strong> ${__("(wird beim Submit als Credit Note erzeugt)")}</div>`,
			"blue",
		);
	}
}

function _warn_if_overridden(frm) {
	if (frm.doc.docstatus !== 0) return;
	const vor = parseFloat(frm.doc.vorauszahlungen || 0);
	const ist = parseFloat(frm.doc.vorauszahlungen_ist || 0);
	if (Math.abs(vor - ist) < 0.01) return; // identisch
	frappe.show_alert(
		{
			message: __("Vorauszahlung wurde manuell überschrieben (IST: {0})", [format_currency(ist, "EUR")]),
			indicator: "orange",
		},
		5,
	);
}
