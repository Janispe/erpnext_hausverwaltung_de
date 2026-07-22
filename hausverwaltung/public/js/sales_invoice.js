frappe.ui.form.on("Sales Invoice", {
	setup(frm) {
		hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm);
	},
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm);
		apply_guthaben_labels(frm);

		if (is_hv_mietrechnung(frm.doc)) {
			frm.add_custom_button(__("Stornieren & korrigiert neu erstellen"), () =>
				start_korrektur(frm)
			);
		}

		if (!can_write_off(frm.doc)) return;

		frm.add_custom_button(__("Abschreiben"), () => {
			window.hv_sales_invoice_writeoff.open_dialog([frm.doc.name], { frm });
		});
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
		hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm);
		apply_guthaben_labels(frm);
	},
	posting_date(frm) {
		hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm);
	},
	validate(frm) {
		hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm);
	},
});

function hv_default_sales_invoice_wertstellungsdatum_from_posting_date(frm) {
	if (!frm.doc || frm.doc.custom_wertstellungsdatum || !frm.doc.posting_date) return;
	frm.set_value("custom_wertstellungsdatum", frm.doc.posting_date);
}

function apply_guthaben_labels(frm) {
	frm.set_df_property("is_return", "label", __("Ist Guthaben"));
	frm.set_df_property("return_against", "label", __("Guthaben zu"));

	window.setTimeout(() => {
		frm.page?.wrapper?.find(".indicator-pill").each(function () {
			const $pill = $(this);
			const text = ($pill.text() || "").trim();
			if (text === __("Return") || text === "Return" || text === "Retoure") {
				$pill.text(__("Guthaben"));
			} else if (text === __("Credit Note Issued") || text === "Credit Note Issued") {
				$pill.text(__("Guthaben ausgestellt"));
			}
		});
	}, 0);
}

function can_write_off(doc) {
	return (
		doc.docstatus === 1 &&
		!doc.is_return &&
		flt(doc.outstanding_amount) > 0.01 &&
		!["Abgeschrieben", "Teilweise bezahlt und abgeschrieben"].includes(doc.status)
	);
}

// Nur für gebuchte Hausverwaltungs-Mietrechnungen (kein Storno/Gutschrift), erkennbar
// am [MV:..]-Remark-Marker oder der mietabrechnung_id.
function is_hv_mietrechnung(doc) {
	return (
		doc.docstatus === 1 &&
		!doc.is_return &&
		((doc.remarks || "").indexOf("[MV:") !== -1 || !!doc.mietabrechnung_id)
	);
}

const KORREKTUR_METHOD =
	"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.korrigiere_mietrechnung";

// Erst Dry-Run (bucht nichts) → Plan im Dialog zeigen → nach Bestätigung ausführen.
function start_korrektur(frm) {
	frappe.call({
		method: KORREKTUR_METHOD,
		args: { sales_invoice: frm.doc.name, dry_run: 1 },
		freeze: true,
		freeze_message: __("Prüfe Korrektur…"),
		callback: (r) => {
			if (r.exc || !r.message) return;
			show_korrektur_dialog(frm, r.message);
		},
	});
}

function show_korrektur_dialog(frm, plan) {
	const ctx = plan.context || {};
	const esc = frappe.utils.escape_html;
	const fmt = (v) => format_currency(flt(v), frm.doc.currency);
	const path_label = plan.frozen
		? __("Gutschrift (festgeschriebene Periode)")
		: plan.paid
			? __("Storno; bestehende Zahlungszuordnung wird gelöst")
			: __("Storno & Neu");

	const rows = [
		[__("Typ"), ctx.typ || "?"],
		[__("Mietvertrag"), ctx.mietvertrag || "?"],
		[__("Monat"), ctx.monat_str || "?"],
		[__("Alter Betrag"), fmt(plan.alter_betrag)],
		[__("Neuer Betrag (aus Staffelmiete)"), fmt(plan.neuer_betrag)],
		[__("Bezahlt"), plan.paid ? __("ja") : __("nein")],
		[__("Periode gesperrt"), plan.frozen ? __("ja") : __("nein")],
		[__("Vorgehen"), path_label],
	];
	if ((plan.payment_entries || []).length) {
		rows.push([__("Payment Entries"), plan.payment_entries.join(", ")]);
	}

	const same = flt(plan.neuer_betrag) === flt(plan.alter_betrag);
	const warn = same
		? `<p class="text-warning">${__(
				"⚠️ Alter und neuer Betrag sind identisch — bitte zuerst die Staffelmiete im Mietvertrag korrigieren."
			)}</p>`
		: "";
	const html = `<table class="table table-bordered" style="margin-bottom:8px">${rows
		.map(
			([k, v]) =>
				`<tr><td style="width:42%"><b>${esc(k)}</b></td><td>${esc(String(v))}</td></tr>`
		)
		.join("")}</table>${warn}`;

	const d = new frappe.ui.Dialog({
		title: __("Mietrechnung korrigieren"),
		fields: [
			{ fieldtype: "HTML", options: html },
			{
				fieldtype: "Check",
				fieldname: "rebook_payments",
				label: __("Bestehende Zahlung direkt der neuen Sollstellung zuordnen"),
				hidden: !plan.paid || plan.frozen,
				default: 0,
				description: __(
					"Die Zahlungsbuchung und ihre Bankverknüpfung bleiben unverändert bestehen. Ein Überschuss bleibt als offenes Guthaben; bei einer Unterdeckung bleibt die neue Sollstellung teilweise offen."
				),
			},
		],
		primary_action_label: __("Korrigieren"),
		primary_action(values) {
			d.hide();
			run_korrektur(frm, values.rebook_payments ? 1 : 0);
		},
	});
	d.show();
}

function run_korrektur(frm, rebook_payments = 0) {
	frappe.call({
		method: KORREKTUR_METHOD,
		args: { sales_invoice: frm.doc.name, dry_run: 0, rebook_payments },
		freeze: true,
		freeze_message: __("Korrigiere…"),
		callback: (r) => {
			if (r.exc || !r.message) return;
			const m = r.message;
			let msg =
				m.path === "gutschrift"
					? __("Gutschrift {0} und neue Rechnung {1} erstellt.", [
							m.gutschrift || "—",
							m.neue_si || "—",
						])
					: __("Rechnung storniert. Neue Rechnung: {0}", [m.neue_si || "—"]);
			if ((m.beibehaltene_payment_entries || []).length) {
				msg += __(" Zahlungsbuchung(en) blieben bestehen: {0}.", [
					m.beibehaltene_payment_entries.join(", "),
				]);
			}
			if ((m.zahlungsuebernahmen || []).length) {
				const allocated = m.zahlungsuebernahmen.reduce(
					(sum, row) => sum + flt(row.zugeordnet),
					0
				);
				msg += __(" Direkt der neuen Sollstellung zugeordnet: {0}.", [
					format_currency(allocated, frm.doc.currency),
				]);
			}
			frappe.show_alert({ message: msg, indicator: "green" }, 7);
			if (m.neue_si) {
				frappe.set_route("Form", "Sales Invoice", m.neue_si);
			} else {
				frm.reload_doc();
			}
		},
	});
}
