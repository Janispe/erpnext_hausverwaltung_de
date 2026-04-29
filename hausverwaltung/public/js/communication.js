frappe.ui.form.on('Communication', {
	refresh(frm) {
		if (frm.is_new() || !is_incoming_email(frm.doc)) {
			return;
		}

		// Paperless-Integration ist noch nicht final — nur System Manager sehen
		// die Buttons. Hausverwalter (und alle anderen) bekommen sie nicht angezeigt.
		const roles = (frappe.user_roles || []);
		if (!roles.includes('System Manager')) {
			return;
		}

	frm.add_custom_button(__('Nach Paperless exportieren'), () => {
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.integrations.paperless.trigger_manual_paperless_export',
			args: { communication: frm.doc.name },
			freeze: true,
				callback: function(r) {
				if (r.message) {
					frappe.show_alert(r.message, 5);
				}
			}
		});
	}, __('Paperless'));

	frm.add_custom_button(__('In Paperless öffnen'), () => {
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.integrations.paperless.get_paperless_link',
			args: { communication: frm.doc.name },
			freeze: true,
			callback: function(r) {
				const payload = r.message || {};
				if (payload.link) {
					window.open(payload.link, '_blank');
					return;
				}
				let msg = __('Kein Paperless-Link gefunden.');
				if (payload.status) {
					msg += ' ' + __('Export-Status: {0}', [payload.status]);
				}
				if (payload.last_error) {
					msg += '<br>' + __('Fehler: {0}', [payload.last_error]);
				}
				frappe.msgprint(msg);
			}
		});
	}, __('Paperless'));
	}
});

function is_incoming_email(doc) {
	const medium = (doc.communication_medium || '').toLowerCase();
	if (medium !== 'email') return false;
	const sent = (doc.sent_or_received || '').toLowerCase();
	if (!['received', 'incoming'].includes(sent)) return false;
	const commType = (doc.communication_type || '').toLowerCase();
	return !commType || ['communication', 'email'].includes(commType);
}
