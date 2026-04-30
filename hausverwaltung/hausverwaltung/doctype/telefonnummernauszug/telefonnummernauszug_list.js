frappe.listview_settings["Telefonnummernauszug"] = {
	primary_action() {
		open_neue_liste_dialog();
	},
	onload(listview) {
		// Label des Primary-Buttons auf "Neue Liste" setzen (Aktion ist via primary_action gehookt).
		const apply_label = () => {
			try {
				listview.page.set_primary_action(
					__("Neue Liste"),
					() => open_neue_liste_dialog(),
					"add"
				);
			} catch (e) {
				// ignore
			}
		};
		apply_label();
		// Frappe ruft set_primary_action nach refresh erneut auf → Label danach wieder setzen.
		setTimeout(apply_label, 0);
	},
};

const open_neue_liste_dialog = () => {
	const dialog = new frappe.ui.Dialog({
		title: __("Neue Telefonliste erstellen"),
		fields: [
			{
				fieldname: "stichtag",
				fieldtype: "Date",
				label: __("Stichtag"),
				reqd: 1,
				default: frappe.datetime.get_today(),
				description: __("Aktive Mietverhältnisse zu diesem Datum werden übernommen."),
			},
			{
				fieldname: "immobilie",
				fieldtype: "Link",
				label: __("Immobilie"),
				options: "Immobilie",
				description: __("Optional. Leer = alle Immobilien."),
			},
			{
				fieldname: "nach_hauptmieter_nachname_sortieren",
				fieldtype: "Check",
				label: __("Nach erstem Hauptmieter-Nachnamen sortieren"),
				description: __(
					"Wohnungen nach dem Nachnamen des ersten Hauptmieters sortieren."
				),
			},
		],
		primary_action_label: __("Erstellen"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.telefonnummernauszug.telefonnummernauszug.erstelle_und_lade",
				args: {
					stichtag: values.stichtag,
					immobilie: values.immobilie || null,
					nach_hauptmieter_nachname_sortieren:
						values.nach_hauptmieter_nachname_sortieren ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Liste wird erstellt…"),
			})
				.then((r) => {
					const res = (r && r.message) || {};
					if (res.name) {
						frappe.show_alert({
							message: __("{0} Einträge geladen.", [res.anzahl || 0]),
							indicator: "green",
						});
						dialog.hide();
						frappe.set_route("Form", "Telefonnummernauszug", res.name);
					}
				})
				.catch((err) => {
					console.error("Telefonliste erstellen fehlgeschlagen", err);
				})
				.finally(() => {
					dialog.enable_primary_action();
				});
		},
	});
	dialog.show();
};
