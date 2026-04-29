const escapeHtml = (value) => {
	if (value === null || value === undefined) {
		return "";
	}
	return frappe.utils.escape_html(String(value));
};

const fmtMoney = (value) => {
	if (value === null || value === undefined || value === "") {
		return "";
	}
	const amount = Number(value || 0);
	try {
		return frappe.format(amount, { fieldtype: "Currency" }, { only_value: true });
	} catch (e) {
		return amount.toFixed(2);
	}
};

const renderPositionen = (frm) => {
	const field = frm.fields_dict?.positionen_vorschau;
	if (!field) {
		return;
	}

	const rows = frm.doc.positionen || [];
	if (!rows.length) {
		frm.set_df_property("positionen_vorschau", "options", "<p>Keine Positionen vorhanden.</p>");
		return;
	}

	const html = `
		<style>
			.euer-doc-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
			.euer-doc-table th, .euer-doc-table td { border: 1px solid #d1d8dd; padding: 6px 8px; }
			.euer-doc-table th { background: #f7fafc; font-weight: 600; }
			.euer-doc-table td.num { text-align: right; white-space: nowrap; }
			.euer-doc-table tr.is-bold td { font-weight: 700; }
			.euer-doc-table tr.is-section td { background: #f7fafc; font-weight: 700; }
			.euer-doc-table tr.is-total td { border-top: 2px solid #98a6ad; }
		</style>
		<table class="euer-doc-table">
			<thead>
				<tr>
					<th>Position</th>
					<th style="text-align:right;">Einnahmen</th>
					<th style="text-align:right;">Ausgaben</th>
					<th style="text-align:right;">Saldo</th>
				</tr>
			</thead>
			<tbody>
				${rows.map((row) => {
					const label = row.bezeichnung || "";
					const isSection = !row.einnahmen && !row.ausgaben && row.saldo === null && !!row.ist_summe;
					const isTotal = /^(Summe |Überschuss\/Verlust)/.test(label);
					const classes = [
						row.ist_summe ? "is-bold" : "",
						isSection ? "is-section" : "",
						isTotal ? "is-total" : "",
					].filter(Boolean).join(" ");
					const indent = "&nbsp;".repeat((Number(row.indent || 0) * 4));
					return `
						<tr class="${classes}">
							<td>${indent}${escapeHtml(label)}</td>
							<td class="num">${fmtMoney(row.einnahmen)}</td>
							<td class="num">${fmtMoney(row.ausgaben)}</td>
							<td class="num">${fmtMoney(row.saldo)}</td>
						</tr>
					`;
				}).join("")}
			</tbody>
		</table>
	`;

	frm.set_df_property("positionen_vorschau", "options", html);
	frm.toggle_display("positionen", false);
};

const toggleAdminOnlyFields = (frm) => {
	const isAdmin = frappe.session.user === "Administrator";
	frm.toggle_display("report_hinweis", isAdmin);
};

frappe.ui.form.on("Einnahmen Ueberschuss Rechnung", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Neu berechnen"), async () => {
				await frm.call("refresh_from_report");
				frm.dirty();
				await frm.save();
			});
		}
		toggleAdminOnlyFields(frm);
		renderPositionen(frm);

		frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
			const presets = window.hausverwaltung && window.hausverwaltung.date_presets;
			if (presets) {
				presets.attach_to_form(frm, {
					from_field: "from_date",
					to_field: "to_date",
					include_gesamt: false,
				});
			}
		});
	},
});
