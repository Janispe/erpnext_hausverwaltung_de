const toggle_immobilien_fields = (frm) => {
	const show = !frm.is_new() && !!frm.doc.immobilien_abrechnung;
	[
		"section_break_immobilie",
		"immobilien_kosten",
	].forEach((field) => frm.toggle_display(field, show));
	// Single-table UI: hide raw tables, show the combined HTML table.
	// Keep the section break visible, otherwise all fields in that section are hidden.
	frm.toggle_display("immobilien_kosten", false);
	frm.toggle_display("abrechnung", false);
	frm.toggle_display("kostenuebersicht", true);
};

const _escape_html = (value) => {
	if (value === null || value === undefined) {
		return "";
	}
	return frappe.utils.escape_html(String(value));
};

const _fmt_money = (value) => {
	const n = Number(value || 0);
	try {
		return frappe.utils.fmt_money(n, null, 2, "EUR");
	} catch (e) {
		return n.toFixed(2) + " EUR";
	}
};

const _fmt_einh = (value, unit) => {
	if (!value && value !== 0) {
		return "&ndash;";
	}
	const n = Number(value || 0);
	if (!unit) {
		return _escape_html(n.toString());
	}
	return `${_escape_html(n.toString())} ${_escape_html(unit)}`;
};

const _collect_art_names = (rows) => {
	const names = new Set();
	(rows || []).forEach((r) => {
		if (r && r.betriebskostenart) {
			names.add(r.betriebskostenart);
		}
	});
	return Array.from(names);
};

const _fetch_verteilungen = async (arts) => {
	if (!arts || !arts.length) {
		return {};
	}
	const res = await frappe.db.get_list("Betriebskostenart", {
		fields: ["name", "verteilung", "schlüssel"],
		filters: { name: ["in", arts] },
		limit: arts.length,
	});
	const map = {};
	(res || []).forEach((row) => {
		if (row && row.name) {
			map[row.name] = {
				verteilung: row.verteilung || "",
				schluessel: row.schlüssel || row.schluessel || "",
			};
		}
	});
	return map;
};

const _get_basis_totals = async (frm) => {
	if (frm.__bk_basis) {
		return frm.__bk_basis;
	}
	if (frm.is_new() || !frm.doc?.name) {
		frm.__bk_basis = { total_qm: 0, total_bewohner: 0, schluessel_totals: {}, wohnung_schluesselwerte: {} };
		return frm.__bk_basis;
	}
	try {
		const res = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_mieter.betriebskostenabrechnung_mieter.get_immobilien_basis",
			args: { name: frm.doc.name },
		});
		const msg = (res && res.message) || {};
		frm.__bk_basis = {
			total_qm: Number(msg.total_qm || 0),
			total_bewohner: Number(msg.total_bewohner || 0),
			schluessel_totals: msg.schluessel_totals || {},
			wohnung_schluesselwerte: msg.wohnung_schluesselwerte || {},
		};
		return frm.__bk_basis;
	} catch (e) {
		frm.__bk_basis = { total_qm: 0, total_bewohner: 0, schluessel_totals: {}, wohnung_schluesselwerte: {} };
		return frm.__bk_basis;
	}
};

const render_kostenuebersicht = async (frm) => {
	const field = frm.fields_dict?.kostenuebersicht;
	if (!field) {
		return;
	}

	const immobilien = frm.doc?.immobilien_kosten || [];
	const abrechnung = frm.doc?.abrechnung || [];
	const arts = Array.from(
		new Set([..._collect_art_names(immobilien), ..._collect_art_names(abrechnung)])
	).sort((a, b) => (a || "").localeCompare(b || ""));

	if (!arts.length) {
		frm.set_df_property("kostenuebersicht", "options", "<p>Keine Abrechnungsposten vorhanden.</p>");
		return;
	}

	const verteilungen = await _fetch_verteilungen(arts);
	const basis = await _get_basis_totals(frm);
	const size_qm = Number(frm.doc?.größe || 0);
	const bewohner = (frm.doc?.mieter || []).length;

	const immobilien_map = {};
	(immobilien || []).forEach((row) => {
		if (!row?.betriebskostenart) {
			return;
		}
		immobilien_map[row.betriebskostenart] = Number(row.betrag || 0);
	});
	const abrechnung_map = {};
	(abrechnung || []).forEach((row) => {
		if (!row?.betriebskostenart) {
			return;
		}
		abrechnung_map[row.betriebskostenart] = Number(row.betrag || 0);
	});

	let sum_gesamt = 0;
	let sum_anteil = 0;
	const rows = arts.map((art) => {
		const meta = verteilungen[art] || {};
		const verteilung = meta.verteilung || "";
		const schluessel = meta.schluessel || "";
		const gesamt = immobilien_map[art] || 0;
		const anteil = abrechnung_map[art] || 0;
		sum_gesamt += gesamt;
		sum_anteil += anteil;

		let einheit = "";
		let anteil_einh = "";
		let gesamt_einh = "";
		if (verteilung === "qm") {
			einheit = "qm";
			gesamt_einh = basis.total_qm;
			anteil_einh = size_qm;
		} else if (verteilung === "Schlüssel" || verteilung === "Schluessel") {
			einheit = "";
			gesamt_einh = Number(basis.schluessel_totals?.[schluessel] || 0);
			anteil_einh = Number(basis.wohnung_schluesselwerte?.[schluessel] || 0);
		} else if (verteilung === "Bewohner") {
			einheit = "";
			gesamt_einh = basis.total_bewohner;
			anteil_einh = bewohner;
		}

		return {
			art,
			verteilung,
			gesamt,
			anteil,
			einh_gesamt: gesamt_einh,
			einh_anteil: anteil_einh,
			einh_unit: einheit,
		};
	});

	const html = `
		<table class="table table-bordered table-hover" style="font-size: 12px; margin-bottom: 8px;">
			<thead>
				<tr>
					<th>${__("Abrechnungsposten")}</th>
					<th>${__("Verteilt nach")}</th>
					<th style="text-align:right;">${__("Gesamt (Einh.)")}</th>
					<th style="text-align:right;">${__("Ihr Anteil (Einh.)")}</th>
					<th style="text-align:right;">${__("Gesamt")}</th>
					<th style="text-align:right;">${__("Ihr Anteil")}</th>
				</tr>
			</thead>
			<tbody>
				${rows
					.map(
						(r) => `
					<tr>
						<td>${_escape_html(r.art)}</td>
						<td>${_escape_html(r.verteilung || "")}</td>
						<td style="text-align:right;">${_fmt_einh(r.einh_gesamt, r.einh_unit)}</td>
						<td style="text-align:right;">${_fmt_einh(r.einh_anteil, r.einh_unit)}</td>
						<td style="text-align:right;">${_fmt_money(r.gesamt)}</td>
						<td style="text-align:right;">${_fmt_money(r.anteil)}</td>
					</tr>
				`
					)
					.join("")}
				<tr>
					<td colspan="4" style="text-align:right;"><strong>${__("Gesamtkosten")}</strong></td>
					<td style="text-align:right;"><strong>${_fmt_money(sum_gesamt)}</strong></td>
					<td style="text-align:right;"><strong>${_fmt_money(sum_anteil)}</strong></td>
				</tr>
			</tbody>
		</table>
	`;

	frm.set_df_property("kostenuebersicht", "options", html);
};

const block_manual_create_and_cancel = (frm) => {
	const info = __(
		"Anlage und Storno laufen über 'Betriebskostenabrechnung Immobilie'. Manuelles Anlegen/Stornieren ist hier gesperrt."
	);
	const can_cancel = !!frm.doc?.__onload?.can_manual_cancel;
	if (frm.is_new()) {
		frm.disable_save();
		frm.set_intro(info, "blue");
	}
	if (frm.doc.docstatus === 1 && frm.page && frm.page.btn_secondary) {
		// Verhindert sichtbare Storno-Buttons auf dem Formular, außer der Nutzer darf explizit stornieren
		if (can_cancel) {
			frm.page.btn_secondary.show();
		} else {
			frm.page.btn_secondary.hide();
			frm.set_intro(info, "blue");
		}
	}
};

const load_immobilien_kosten = (frm, attempt = 1) => {
	const table = frm.fields_dict.immobilien_kosten;
	if (!table) {
		return Promise.resolve();
	}
	// Vorherigen Dirty-Status merken, damit wir Nutzeränderungen nicht überschreiben.
	const was_dirty = frm.is_dirty();
	frm.set_df_property("immobilien_kosten", "cannot_add_rows", true);
	frm.set_df_property("immobilien_kosten", "cannot_delete_rows", true);
	frm.set_df_property("immobilien_kosten", "read_only", true);
	if (frm.is_new() || !frm.doc.immobilien_abrechnung) {
		frm.clear_table("immobilien_kosten");
		frm.refresh_field("immobilien_kosten");
		render_kostenuebersicht(frm);
		return Promise.resolve();
	}
	return frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_mieter.betriebskostenabrechnung_mieter.get_immobilien_kosten",
			args: { name: frm.doc.name },
		})
		.then((r) => {
			const rows = (r && r.message) || [];
			frm.clear_table("immobilien_kosten");
			rows.forEach((row) => {
				const child = frm.add_child("immobilien_kosten");
				child.betriebskostenart = row.betriebskostenart;
				child.betrag = row.betrag;
			});
			frm.refresh_field("immobilien_kosten");
			render_kostenuebersicht(frm);
			if (frm.doc && frm.toolbar) {
				frm.doc.__unsaved = was_dirty ? 1 : 0;
				frm.toolbar.refresh();
			}
			if (frm.refresh_header) {
				frm.refresh_header();
			}
		})
		.catch((err) => {
			// Einmal retryen, falls das Doc gerade frisch geladen wird
			if (attempt < 2) {
				return new Promise((resolve) =>
					setTimeout(() => resolve(load_immobilien_kosten(frm, attempt + 1)), 400)
				);
			}
			console.error("Immobilien-Kosten laden fehlgeschlagen", err);
			let detail = "";
			try {
				const rawServer = err?._server_messages || err?.__server_messages;
				if (rawServer) {
					const msgs = JSON.parse(rawServer);
					const cleaned = (Array.isArray(msgs) ? msgs : [msgs])
						.map((m) => {
							try {
								const parsed = JSON.parse(m);
								return parsed?.message || m;
							} catch {
								return m;
							}
						})
						.join("\n");
					detail = cleaned || detail;
				}
				if (!detail && err?.message) {
					detail = err.message;
				}
				if (!detail && err?.exc) {
					detail = err.exc;
				}
				if (!detail && typeof err === "string") {
					detail = err;
				}
			} catch {
				// ignore
			}
			frappe.msgprint({
				title: __("Fehler"),
				indicator: "red",
				message:
					__("Kosten aus der Immobilienabrechnung konnten nicht geladen werden.") +
					(detail
						? "<br><small>" + frappe.utils.escape_html(detail) + "</small>"
						: "<br><small>Details siehe Browser-Konsole.</small>"),
			});
		});
};


frappe.ui.form.on("Betriebskostenabrechnung Mieter", {
	refresh(frm) {
		block_manual_create_and_cancel(frm);
		toggle_immobilien_fields(frm);
		if (frm.is_new()) {
			load_immobilien_kosten(frm);
			return;
		}
		if (!frm.__bk_reloading) {
			frm.__bk_reloading = true;
			frm.reload_doc();
			return;
		}
		frm.__bk_reloading = false;
		toggle_immobilien_fields(frm);
		load_immobilien_kosten(frm);
	},
	abrechnung: function (frm) {
		render_kostenuebersicht(frm);
	},
});
