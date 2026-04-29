// frappe.ui.form.on("Mietvertrag", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("Mietvertrag", {
	setup(frm) {
		frm.set_query("kontakt", "kontoverbindungen", () => {
			const contacts = (frm.doc.mieter || []).map((row) => row.mieter);
			if (contacts.length) {
				return { filters: { name: ["in", contacts] } };
			}
			return {};
		});
		frm.set_query("betriebskostenart", "festbetraege", () => ({
			filters: { verteilung: "Festbetrag" },
		}));
	},
	refresh(frm) {
		console.log("✅ mietvertrag.js wurde geladen");

		update_bruttomiete(frm);
		hide_staffelmiete_art_column(frm, "kaution");
		ensure_staffel_highlight_css();
		highlight_current_staffeln(frm);

		// Felder ausblenden je nach Wohnung
		if (frm.doc.wohnung) {
			frappe.db.get_doc("Wohnung", frm.doc.wohnung).then(function (wohnung) {
				frm.set_df_property(
					"betriebskosten",
					"hidden",
					!wohnung.betriebskostenabrechnung_durch_vermieter
				);
				frm.set_df_property(
					"heizkosten",
					"hidden",
					!wohnung.heizkostenabrechnung_durch_vermieter
				);
			});
		} else {
			frm.set_df_property("betriebskosten", "hidden", 1);
			frm.set_df_property("heizkosten", "hidden", 1);
		}

		add_paperless_button(frm);
		add_mieterwechsel_start_button_from_mietvertrag(frm);
		add_mieterkonto_button_from_mietvertrag(frm);

		frm.add_custom_button(__("Staffelmieten sortieren"), async () => {
			sort_staffel_table_by_von(frm, "miete");
			sort_staffel_table_by_von(frm, "betriebskosten");
			sort_staffel_table_by_von(frm, "heizkosten");
			sort_staffel_table_by_von(frm, "untermietzuschlag");
			sort_staffel_table_by_von(frm, "kaution");

			frm.refresh_fields([
				"miete",
				"betriebskosten",
				"heizkosten",
				"untermietzuschlag",
				"kaution",
			]);
			highlight_current_staffeln(frm);
		});
	},

	von(frm) {
		update_bruttomiete(frm);
	},
	bis(frm) {
		update_bruttomiete(frm);
	},
	miete_add(frm) {
		update_bruttomiete(frm);
	},
	miete_remove(frm) {
		update_bruttomiete(frm);
	},
	betriebskosten_add(frm) {
		update_bruttomiete(frm);
	},
	betriebskosten_remove(frm) {
		update_bruttomiete(frm);
	},
	heizkosten_add(frm) {
		update_bruttomiete(frm);
	},
	heizkosten_remove(frm) {
		update_bruttomiete(frm);
	},
	untermietzuschlag_add(frm) {
		update_bruttomiete(frm);
	},
	untermietzuschlag_remove(frm) {
		update_bruttomiete(frm);
	},

	wohnung(frm) {
		if (frm.doc.wohnung) {
			frappe.db.get_doc("Wohnung", frm.doc.wohnung).then(function (wohnung) {
				frm.set_df_property(
					"betriebskosten",
					"hidden",
					!wohnung.betriebskostenabrechnung_durch_vermieter
				);
				frm.set_df_property(
					"heizkosten",
					"hidden",
					!wohnung.heizkostenabrechnung_durch_vermieter
				);
			});
		} else {
			frm.set_df_property("betriebskosten", "hidden", 1);
			frm.set_df_property("heizkosten", "hidden", 1);
		}
	},
});

function hide_staffelmiete_art_column(frm, tableFieldname) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid || typeof grid.update_docfield_property !== "function") return;

	grid.update_docfield_property("art", "in_list_view", 0);
	frm.refresh_field(tableFieldname);
}

frappe.ui.form.on("Staffelmiete", {
	von(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
	miete(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
	art(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
});

function _bruttomiete_stichtag_obj(frm) {
	const todayObj = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	let stichtag = todayObj;

	if (frm.doc.von) {
		const vonObj = frappe.datetime.str_to_obj(frm.doc.von);
		if (vonObj > stichtag) stichtag = vonObj;
	}
	if (frm.doc.bis) {
		const bisObj = frappe.datetime.str_to_obj(frm.doc.bis);
		if (bisObj < stichtag) stichtag = bisObj;
	}
	return stichtag;
}

function _staffelbetrag_am(rows, stichtagObj) {
	let bestVon = null;
	let bestValue = 0.0;

	(rows || []).forEach((row) => {
		if (!row.von) return;
		const vonObj = frappe.datetime.str_to_obj(row.von);
		if (vonObj <= stichtagObj && (bestVon === null || vonObj > bestVon)) {
			bestVon = vonObj;
			bestValue = flt(row.miete);
		}
	});

	return flt(bestValue);
}

function update_bruttomiete(frm) {
	if (!frm || frm.doctype !== "Mietvertrag") return;
	if (!frm.doc) return;

	const stichtagObj = _bruttomiete_stichtag_obj(frm);
	const total =
		_staffelbetrag_am(frm.doc.miete, stichtagObj) +
		_staffelbetrag_am(frm.doc.betriebskosten, stichtagObj) +
		_staffelbetrag_am(frm.doc.heizkosten, stichtagObj) +
		_staffelbetrag_am(frm.doc.untermietzuschlag, stichtagObj);

	const current = flt(frm.doc.bruttomiete);
	const next = flt(total);
	if (Math.abs(current - next) < 0.00001) {
		highlight_current_staffeln(frm);
		return;
	}
	frm.set_value("bruttomiete", next);
	highlight_current_staffeln(frm);
}

function add_paperless_button(frm) {
	if (frm.is_new()) {
		return;
	}

	// Paperless-Integration ist noch nicht final — nur System Manager sehen den
	// Button. Hausverwalter (und alle anderen) bekommen ihn nicht angezeigt.
	const roles = (frappe.user_roles || []);
	if (!roles.includes('System Manager')) {
		return;
	}

	frm.add_custom_button(__('Paperless NGX'), () => {
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.get_mietvertrag_paperless_link',
			args: { mietvertrag: frm.doc.name },
			freeze: true,
			callback: function(r) {
				const link = r.message;
				if (!link) {
					frappe.msgprint(__('Kein Paperless-Link gefunden.'));
					return;
				}
				window.open(link, '_blank');
			},
			error: function() {
				frappe.msgprint(__('Paperless-Link konnte nicht geladen werden.'));
			}
		});
	}, __('Paperless'));
}

function add_mieterwechsel_start_button_from_mietvertrag(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__("Mieterwechsel starten"), () => {
		frappe.new_doc("Mieterwechsel", {
			prozess_typ: "Mieterwechsel",
			wohnung: frm.doc.wohnung || undefined,
			alter_mietvertrag: frm.doc.name,
			auszugsdatum: frm.doc.bis || undefined,
			einzugsdatum: frm.doc.bis || undefined,
			quelle_doctype: "Mietvertrag",
			quelle_name: frm.doc.name,
		});
	}, __("Workflow"));
}

function add_mieterkonto_button_from_mietvertrag(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__("Mieterkonto"), () => {
		const company = frappe.defaults.get_user_default("Company");
		if (!company) {
			frappe.msgprint(__("Bitte zuerst eine Standard-Firma setzen."));
			return;
		}
		if (!frm.doc.kunde) {
			frappe.msgprint(__("Dieser Mietvertrag hat keinen Mieter/Debitor."));
			return;
		}

		frappe.set_route("query-report", "Mieterkonto", {
			company,
			customer: frm.doc.kunde,
			from_date: frm.doc.von || frappe.datetime.year_start(),
			to_date: frm.doc.bis || frappe.datetime.get_today(),
		});
	}, __("Accounting"));
}

function sort_staffel_table_by_von(frm, tableFieldname) {
	if (!frm || !frm.doc) return;
	const rows = frm.doc[tableFieldname] || [];
	if (rows.length < 2) return;

	rows.sort((a, b) => {
		if (!a.von && !b.von) return 0;
		if (!a.von) return 1;
		if (!b.von) return -1;
		const av = frappe.datetime.str_to_obj(a.von);
		const bv = frappe.datetime.str_to_obj(b.von);
		return av - bv;
	});

	rows.forEach((row, idx) => {
		row.idx = idx + 1;
	});
}

function ensure_staffel_highlight_css() {
	if (window.__hv_staffel_highlight_css_loaded) return;
	window.__hv_staffel_highlight_css_loaded = true;

	const style = document.createElement("style");
	style.type = "text/css";
	style.textContent = `
		.hv-current-staffel-row {
			background: rgba(255, 193, 7, 0.12) !important;
		}
		.hv-current-staffel-row .grid-static-col,
		.hv-current-staffel-row .grid-row-check {
			background: transparent !important;
		}
		.hv-current-staffel-row .static-area .form-control,
		.hv-current-staffel-row .grid-static-col .static-area {
			font-weight: 600;
		}
	`;
	document.head.appendChild(style);
}

function highlight_current_staffeln(frm) {
	if (!frm || frm.doctype !== "Mietvertrag" || !frm.doc) return;

	// Delay until grids are rendered (especially on first load)
	setTimeout(() => {
		highlight_current_staffel_row(frm, "miete");
		highlight_current_staffel_row(frm, "betriebskosten");
		highlight_current_staffel_row(frm, "heizkosten");
		highlight_current_staffel_row(frm, "untermietzuschlag");
		highlight_current_staffel_row(frm, "kaution");
	}, 0);
}

function highlight_current_staffel_row(frm, tableFieldname) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid) return;

	const rows = frm.doc[tableFieldname] || [];
	if (!rows.length) return;

	const stichtagObj = _bruttomiete_stichtag_obj(frm);

	let currentRow = null;
	let bestVon = null;
	rows.forEach((row) => {
		if (!row.von) return;
		const vonObj = frappe.datetime.str_to_obj(row.von);
		if (vonObj <= stichtagObj && (bestVon === null || vonObj > bestVon)) {
			bestVon = vonObj;
			currentRow = row;
		}
	});

	(grid.grid_rows || []).forEach((gridRow) => {
		const wrapper = gridRow && gridRow.wrapper;
		if (!wrapper) return;
		if (typeof wrapper.removeClass === "function") wrapper.removeClass("hv-current-staffel-row");
		else if (wrapper.classList) wrapper.classList.remove("hv-current-staffel-row");
	});

	if (!currentRow) return;

	(grid.grid_rows || []).forEach((gridRow) => {
		if (!gridRow || !gridRow.doc || !gridRow.wrapper) return;
		if (gridRow.doc.name === currentRow.name) {
			const wrapper = gridRow.wrapper;
			if (typeof wrapper.addClass === "function") wrapper.addClass("hv-current-staffel-row");
			else if (wrapper.classList) wrapper.classList.add("hv-current-staffel-row");
		}
	});
}
