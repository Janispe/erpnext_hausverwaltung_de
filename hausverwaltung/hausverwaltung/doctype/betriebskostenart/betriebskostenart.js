frappe.ui.form.on("Betriebskostenart", {
	refresh(frm) {
		toggle_betriebskostenart_fields(frm);
	},
	verteilung(frm) {
		toggle_betriebskostenart_fields(frm);
	}
});

function toggle_betriebskostenart_fields(frm) {
	const sel = frm.doc.verteilung || "";
	const showSchluessel = sel === "Schlüssel";
	const showFestbetragHint = sel === "Festbetrag";

	// Show/hide fields
	frm.toggle_display("schlüssel", showSchluessel);
	if (showFestbetragHint) {
		frm.set_intro(
			__(
				"Festbeträge werden im Mietvertrag-Tab 'Festbeträge' pro Mietvertrag und Gültigkeitszeitraum gepflegt."
			),
			"blue"
		);
	} else {
		frm.set_intro("");
	}
}
