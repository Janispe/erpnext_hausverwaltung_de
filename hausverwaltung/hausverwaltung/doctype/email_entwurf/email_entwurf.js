frappe.ui.form.on("Email Entwurf", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		add_email_action_buttons(frm);
	},
});

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
