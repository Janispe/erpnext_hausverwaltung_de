frappe.ui.form.on('Wohnung', {
	refresh(frm) {
		add_paperless_button(frm);
		add_zaehler_zuordnen_button(frm);
		add_mieterwechsel_start_button_from_wohnung(frm);
		render_aktuelle_zaehler(frm);
		load_mietvertraege(frm);
	},

	// Handle the custom button field "Zustand Einrichten / Verändern"
	zustand_einrichten__verändern(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__('Bitte zuerst die Wohnung speichern.'));
			return;
		}

		// Try to get or create an initial Wohnungszustand and route to it
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.get_or_create_initial_zustand',
			args: { wohnung: frm.doc.name },
			freeze: true,
			callback: function(r) {
				if (r.message) {
					frappe.set_route('Form', 'Wohnungszustand', r.message);
				}
			}
		});
	}
});

function add_paperless_button(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__('Paperless NGX'), () => {
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.get_paperless_link',
			args: { wohnung: frm.doc.name },
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

function add_zaehler_zuordnen_button(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__('Zähler zuordnen'), () => {
		frappe.prompt(
			[
				{
					fieldname: 'zaehler',
					fieldtype: 'Link',
					label: __('Zähler'),
					options: 'Zaehler',
					reqd: 1
				},
				{
					fieldname: 'notiz',
					fieldtype: 'Small Text',
					label: __('Notiz')
				}
			],
			(values) => {
				frappe.call({
					method: 'hausverwaltung.hausverwaltung.doctype.zaehler_zuordnung.zaehler_zuordnung.assign_zaehler_to_wohnung',
					args: {
						wohnung: frm.doc.name,
						zaehler: values.zaehler,
						notiz: values.notiz
					},
					freeze: true,
					callback: function(r) {
						if (r.message) {
							frappe.set_route('Form', 'Zaehler Zuordnung', r.message);
						}
					}
				});
			},
			__('Zähler zuordnen'),
			__('Zuordnen')
		);
	}, __('Zähler'));
}

function add_mieterwechsel_start_button_from_wohnung(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__('Mieterwechsel starten'), () => {
		frappe.prompt(
			[
				{
					fieldname: 'prozess_typ',
					fieldtype: 'Select',
					label: __('Prozess-Typ'),
					options: 'Mieterwechsel\nErstvermietung',
					default: 'Mieterwechsel',
					reqd: 1
				}
			],
			(values) => {
				const isErstvermietung = (values.prozess_typ || '').trim() === 'Erstvermietung';
				const payload = {
					prozess_typ: values.prozess_typ,
					wohnung: frm.doc.name,
					quelle_doctype: 'Wohnung',
					quelle_name: frm.doc.name,
				};
				if (isErstvermietung) {
					payload.neue_adresse_altmieter_erfasst = 1;
				}
				frappe.new_doc('Mieterwechsel', payload);
			},
			__('Mieterwechsel starten'),
			__('Starten')
		);
	}, __('Workflow'));
}

function render_aktuelle_zaehler(frm) {
	if (!frm.fields_dict.aktuelle_zaehler) {
		return;
	}
	if (frm.is_new()) {
		frm.fields_dict.aktuelle_zaehler.$wrapper.html('');
		return;
	}

	frm.fields_dict.aktuelle_zaehler.$wrapper.html(
		`<div class="text-muted">${__('Lade aktuelle Zähler...')}</div>`
	);

	frappe.call({
		method: 'hausverwaltung.hausverwaltung.doctype.zaehler_zuordnung.zaehler_zuordnung.get_aktive_zaehler_fuer_wohnung',
		args: { wohnung: frm.doc.name },
		callback: function(r) {
			const rows = (r && r.message) || [];
			if (!rows.length) {
				frm.fields_dict.aktuelle_zaehler.$wrapper.html(
					`<div class="text-muted">${__('Keine aktiven Zähler zugeordnet.')}</div>`
				);
				return;
			}

			const esc = frappe.utils.escape_html;
			const makeLink = (doctype, name, label) => {
				const url = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
				return `<a href="${url}">${esc(label || name)}</a>`;
			};

			let html = `<div class="table-responsive"><table class="table table-bordered" style="margin:0">`;
			html += `<thead><tr>`;
			html += `<th>${__('Zähler')}</th>`;
			html += `<th>${__('Art')}</th>`;
			html += `<th>${__('Zählernummer')}</th>`;
			html += `<th>${__('Standort')}</th>`;
			html += `<th>${__('Von')}</th>`;
			html += `<th>${__('Bis')}</th>`;
			html += `<th>${__('Zuordnung')}</th>`;
			html += `</tr></thead><tbody>`;

			rows.forEach((row) => {
				html += `<tr>`;
				html += `<td>${makeLink('Zaehler', row.zaehler, row.zaehler)}</td>`;
				html += `<td>${esc(row.zaehlerart || '')}</td>`;
				html += `<td>${esc(row.zaehlernummer || '')}</td>`;
				html += `<td>${esc(row.standort_beschreibung || '')}</td>`;
				html += `<td>${esc(row.von || '')}</td>`;
				html += `<td>${esc(row.bis || '')}</td>`;
				html += `<td>${makeLink('Zaehler Zuordnung', row.zuordnung, row.zuordnung)}</td>`;
				html += `</tr>`;
			});

			html += `</tbody></table></div>`;
			frm.fields_dict.aktuelle_zaehler.$wrapper.html(html);
		}
	});
}

function load_mietvertraege(frm) {
	const control = frm.fields_dict.mietvertraege_alle;
	if (!control) {
		return;
	}

	const was_dirty = frm.is_dirty();
	frm.set_df_property("mietvertraege_alle", "cannot_add_rows", true);
	frm.set_df_property("mietvertraege_alle", "cannot_delete_rows", true);
	frm.set_df_property("mietvertraege_alle", "read_only", true);

	if (frm.is_new()) {
		frm.clear_table("mietvertraege_alle");
		frm.refresh_field("mietvertraege_alle");
		return;
	}

	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.get_mietvertraege_fuer_wohnung",
		args: { wohnung: frm.doc.name }
	}).then((r) => {
		const rows = (r && r.message) || [];
		frm.clear_table("mietvertraege_alle");
		rows.forEach((row) => {
			const child = frm.add_child("mietvertraege_alle");
			child.mietvertrag = row.mietvertrag;
			child.von = row.von;
			child.bis = row.bis;
			child.status = row.status;
			child.kunde = row.kunde;
		});
		frm.refresh_field("mietvertraege_alle");

		if (frm.doc && frm.toolbar) {
			frm.doc.__unsaved = was_dirty ? 1 : 0;
			frm.toolbar.refresh();
		}
	}).catch((err) => {
		console.error("Mietverträge laden fehlgeschlagen", err);
		frappe.msgprint({
			title: __("Fehler"),
			message: __("Mietverträge konnten nicht geladen werden."),
			indicator: "red"
		});
	});
}
