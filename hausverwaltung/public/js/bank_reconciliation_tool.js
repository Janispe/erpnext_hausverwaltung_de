// Override des Standard-Buttons „Kontoauszug hochladen" im Bank Reconciliation
// Tool: statt des ERPNext Bank-Statement-Imports öffnen wir den eigenen
// Bankauszug Import (Postbank-CSV mit Party-Zuordnung).
//
// Frappe merged mehrere `frappe.ui.form.on()`-Handler. Der ERPNext-Refresh fügt
// den Standard-Button hinzu — danach läuft unser Refresh und ersetzt ihn.
frappe.ui.form.on('Bank Reconciliation Tool', {
	refresh(frm) {
		frm.remove_custom_button(__('Upload Bank Statement'));
		frm.add_custom_button(__('Kontoauszug hochladen'), () => {
			frappe.new_doc('Bankauszug Import', {
				bank_account: frm.doc.bank_account || '',
			});
		});
	},
});
