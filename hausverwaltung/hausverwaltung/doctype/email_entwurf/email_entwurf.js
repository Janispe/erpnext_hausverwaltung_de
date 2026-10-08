frappe.ui.form.on("Email Entwurf", {
	refresh(frm) {
		if (frm.doc.delivery_backend === "Stalwart") {
			["recipients", "cc", "bcc", "subject", "message", "reference_doctype", "reference_name", "status", "send_after"].forEach((field) => frm.set_df_property(field, "read_only", 1));
			frm.set_intro(__("Der Entwurf liegt im Mailpostfach. Bitte in Thunderbird bearbeiten und versenden. Dieser Text zeigt den ursprünglich erzeugten Vorschlag."), "blue");
			add_mailbox_tracking_buttons(frm);
			return;
		}
		if (frm.is_new()) {
			return;
		}
		add_email_action_buttons(frm);
	},
});

function add_mailbox_tracking_buttons(frm) {
	if (frm.is_new() || frm.doc.status !== "Draft" || !frappe.user_roles.some((role) => ["System Manager", "Hausverwalter"].includes(role))) return;
	const run = (action) => frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.email_entwurf.email_entwurf.manage_mailbox_tracking",
		args: { docname: frm.doc.name, action },
		freeze: true,
	}).then(() => frm.reload_doc());
	if (frm.doc.mailbox_sync_paused) {
		if (frm.doc.remote_creation_started || frm.doc.provider_draft_id || frm.doc.mailbox_pause_reason === "Manual") {
			frm.add_custom_button(__("Abgleich fortsetzen"), () => run("resume"), __("Postfachabgleich"));
		}
	} else {
		frm.add_custom_button(__("Abgleich pausieren"), () => run("pause"), __("Postfachabgleich"));
	}
	frm.add_custom_button(__("Auftrag verwerfen"), () => {
		frappe.confirm(__("Den ERPNext-Auftrag schließen? Eine vorhandene Mail bleibt im Postfach. Die ursprüngliche request_id bleibt gesperrt."), () => run("discard"));
	}, __("Postfachabgleich"));
}

function add_email_action_buttons(frm) {
	const status = (frm.doc.status || "").trim();
	const options = [];
	if (status === "Draft") options.push({ label: "Queue", action: "queue" });
	if (status === "Queued") {
		options.push({ label: "Mark Sent", action: "mark_sent" });
		options.push({ label: "Cancel", action: "cancel" });
	}
	if (status === "Draft") options.push({ label: "Cancel", action: "cancel" });

	if (!options.length) {
		return;
	}

	frm.add_custom_button(__("Workflow-Aktion"), () => {
		frappe.prompt(
			[
				{
					fieldname: "action_label",
					label: __("Aktion"),
					fieldtype: "Select",
					reqd: 1,
					options: options.map((o) => o.label).join("\n"),
				},
			],
			(values) => {
				const selected = options.find((o) => o.label === values.action_label);
				if (!selected) return;

				const run = (payload = {}) =>
					frappe
						.call({
							method: "hausverwaltung.hausverwaltung.doctype.email_entwurf.email_entwurf.dispatch_workflow_action",
							args: {
								docname: frm.doc.name,
								action: selected.action,
								payload_json: JSON.stringify(payload || {}),
							},
							freeze: true,
						})
						.then(() => frm.reload_doc());

				if (selected.action === "queue") {
					frappe.prompt(
						[
							{
								fieldname: "send_after",
								label: __("Senden nach"),
								fieldtype: "Datetime",
								reqd: 0,
							},
						],
						(v) => run({ send_after: v.send_after || null }),
						__("Queue"),
						__("Ausfuehren")
					);
					return;
				}

				run({});
			},
			__("Workflow-Aktion"),
			__("Ausfuehren")
		);
	}, __("Workflow"));
}
