// List-View für „Heizkostenabrechnung Immobilie".
//
// Override des Standard-„+ Hinzufügen"-Buttons: statt eines leeren Form öffnet
// sich der Wizard-Dialog mit nur den nötigen Pflichtfeldern → beim Bestätigen
// wird das Doc + alle Mieter-Drafts in einem Rutsch erzeugt. Auch der
// Empty-State-Button „Erstellen Sie Ihren ersten…" ruft den Wizard auf, weil
// Frappe beide Pfade durch ``listview.make_new_doc`` leitet.
//
// Wenn ein Power-User das alte „leeres Form"-Verhalten braucht, kann er
// direkt zur URL ``/app/heizkostenabrechnung-immobilie/new?immobilie=…``
// navigieren oder die Frappe-API ``frappe.new_doc("Heizkostenabrechnung
// Immobilie")`` aus der Console nutzen.

frappe.listview_settings["Heizkostenabrechnung Immobilie"] = {
	hide_name_column: false,
	add_fields: ["status", "immobilie", "von", "bis"],

	get_indicator(doc) {
		const map = {
			Eingang: ["Eingang", "blue", "status,=,Eingang"],
			"Mieter-Drafts angelegt": ["Mieter-Drafts angelegt", "orange", "status,=,Mieter-Drafts angelegt"],
			Submittet: ["Submittet", "green", "status,=,Submittet"],
			Versendet: ["Versendet", "purple", "status,=,Versendet"],
		};
		return map[doc.status];
	},

	onload(listview) {
		// Override: standard „+ Hinzufügen" + Empty-State-Button öffnen den Wizard
		listview.make_new_doc = function () {
			_show_wizard(listview);
		};
	},
};

function _show_wizard(listview) {
	const heute = frappe.datetime.get_today();
	const vorjahr = frappe.datetime.add_months(heute, -12);
	const default_von = vorjahr.substring(0, 4) + "-01-01";
	const default_bis = vorjahr.substring(0, 4) + "-12-31";

	const dialog = new frappe.ui.Dialog({
		title: __("Neue Heizkostenabrechnung anlegen"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options:
					`<div class="alert alert-info" style="margin-bottom:15px">
						<strong>${__("So gehst Du vor:")}</strong><br>
						${__("1. Fülle hier die Pflichtfelder aus → Klick auf <strong>Anlegen</strong>")}<br>
						${__("2. Im neuen Doc ist die Mieter-Tabelle schon befüllt — Du musst nur noch <code>Kosten gesamt</code> pro Mieter aus der Wärmedienst-Abrechnung eintragen")}<br>
						${__("3. <strong>Submit</strong> → alle Sales Invoices werden automatisch gebucht")}
					</div>`,
			},
			{
				fieldname: "immobilie",
				label: __("Immobilie"),
				fieldtype: "Link",
				options: "Immobilie",
				reqd: 1,
				description: __("Welche Immobilie wird abgerechnet?"),
			},
			{
				fieldname: "section_periode",
				fieldtype: "Section Break",
				label: __("Abrechnungszeitraum"),
			},
			{
				fieldname: "von",
				label: __("Von"),
				fieldtype: "Date",
				reqd: 1,
				default: default_von,
				description: __("Anfang der Abrechnungsperiode"),
			},
			{
				fieldname: "col_bis",
				fieldtype: "Column Break",
			},
			{
				fieldname: "bis",
				label: __("Bis"),
				fieldtype: "Date",
				reqd: 1,
				default: default_bis,
				description: __("Ende der Abrechnungsperiode"),
			},
			{
				fieldname: "section_dienst",
				fieldtype: "Section Break",
				label: __("Wärmedienst (optional)"),
				description: __("Diese Felder kannst Du auch später noch im Doc ergänzen."),
			},
			{
				fieldname: "waermedienst",
				label: __("Wärmedienst (Lieferant)"),
				fieldtype: "Link",
				options: "Supplier",
				description: __("z.B. Brunata, Techem, ista, Minol — als Lieferant angelegt"),
			},
			{
				fieldname: "col_ref",
				fieldtype: "Column Break",
			},
			{
				fieldname: "waermedienst_referenz",
				label: __("Sammel-Abrechnungs-Nr."),
				fieldtype: "Data",
				description: __("Referenz-Nr. vom Wärmedienst (falls vorhanden)"),
			},
		],
		primary_action_label: __("Anlegen + Mieter laden"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.create_with_drafts",
				args: values,
				freeze: true,
				freeze_message: __("Doc wird angelegt + Mieter-Drafts geladen…"),
				callback(r) {
					if (!r || !r.message) {
						dialog.enable_primary_action();
						return;
					}
					const m = r.message;
					dialog.hide();
					const lines = [
						__("Doc <strong>{0}</strong> angelegt", [m.name]),
						__("<strong>{0}</strong> Mieter-Drafts geladen", [m.drafts_created]),
					];
					if (m.no_wohnung && m.no_wohnung.length) {
						lines.push(__("{0} Mietverträge ohne Customer/Wohnung übersprungen", [m.no_wohnung.length]));
					}
					lines.push("<br>" + __("Du landest jetzt im neuen Doc — bitte <code>Kosten gesamt</code> pro Mieter aus der Wärmedienst-Abrechnung eintragen + <strong>Submit</strong>."));
					frappe.msgprint({
						title: __("Sammel-Abrechnung angelegt"),
						message: lines.join("<br>"),
						indicator: "green",
					});
					frappe.set_route("Form", "Heizkostenabrechnung Immobilie", m.name);
				},
				error() {
					dialog.enable_primary_action();
				},
			});
		},
	});
	dialog.show();
}
