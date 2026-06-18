frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		hv_render_purchase_invoice_amendments(frm);
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
});

const hv_escape_html = (value) => {
	const text = value === undefined || value === null ? "" : String(value);
	if (frappe.utils?.escape_html) {
		return frappe.utils.escape_html(text);
	}
	return text
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#039;");
};

const hv_status_label = (row) => {
	if (row.docstatus === 2) return __("Storniert");
	if (row.docstatus === 1) return row.status || __("Gebucht");
	return __("Entwurf");
};

const hv_status_color = (row) => {
	if (row.docstatus === 2) return "red";
	if (row.status === "Paid") return "green";
	if (row.docstatus === 1) return "blue";
	return "orange";
};

async function hv_render_purchase_invoice_amendments(frm) {
	if (frm.is_new() || !frm.doc?.name) return;

	const token = `${frm.doc.name}:${frm.doc.modified || ""}`;
	frm.__hv_purchase_invoice_amendment_token = token;

	try {
		const response = await frappe.call({
			method:
				"hausverwaltung.hausverwaltung.utils.purchase_invoice_amendments.get_purchase_invoice_amendment_chain",
			args: { name: frm.doc.name },
		});
		if (frm.__hv_purchase_invoice_amendment_token !== token) return;

		const data = response.message || {};
		if (!data.has_chain) return;

		hv_add_purchase_invoice_amendment_buttons(frm, data);
		hv_set_purchase_invoice_amendment_intro(frm, data);
	} catch (error) {
		// Die normale Rechnungserfassung soll nicht durch eine reine Navigationshilfe blockiert werden.
		console.warn("Purchase Invoice amendment chain could not be loaded", error);
	}
}

function hv_add_purchase_invoice_amendment_buttons(frm, data) {
	if (data.previous && data.previous !== frm.doc.name) {
		frm.add_custom_button(__("Vorgänger öffnen"), () => {
			frappe.set_route("Form", "Purchase Invoice", data.previous);
		}, __("Amendment"));
	}

	if (data.latest && data.latest !== frm.doc.name) {
		frm.add_custom_button(__("Aktuelle Version öffnen"), () => {
			frappe.set_route("Form", "Purchase Invoice", data.latest);
		}, __("Amendment"));
	}

	for (const next_name of data.next || []) {
		if (!next_name || next_name === frm.doc.name) continue;
		frm.add_custom_button(__("Nachfolger öffnen"), () => {
			frappe.set_route("Form", "Purchase Invoice", next_name);
		}, __("Amendment"));
	}
}

function hv_set_purchase_invoice_amendment_intro(frm, data) {
	const chain = data.chain || [];
	const rows = chain
		.map((row) => {
			const marker = row.is_current ? `<strong>${__("aktuell geöffnet")}</strong>` : "";
			const padding = Math.max(0, row.depth || 0) * 18;
			return `
				<div style="display:flex;align-items:center;gap:8px;padding:2px 0 2px ${padding}px;">
					<a href="#" data-hv-pi-amendment-link="${hv_escape_html(row.name)}">${hv_escape_html(row.name)}</a>
					<span class="indicator-pill ${hv_status_color(row)}">${hv_escape_html(hv_status_label(row))}</span>
					${marker}
				</div>
			`;
		})
		.join("");

	const latest_part =
		data.latest && data.latest !== frm.doc.name
			? ` ${__("Aktuelle Version")}: <a href="#" data-hv-pi-amendment-link="${hv_escape_html(data.latest)}">${hv_escape_html(data.latest)}</a>.`
			: "";

	frm.set_intro(
		`
			<div>
				<div><strong>${__("Amendment-Kette")}</strong>.${latest_part}</div>
				<div style="margin-top:6px;">${rows}</div>
			</div>
		`,
		"blue"
	);

	setTimeout(() => {
		$(frm.wrapper)
			.find("[data-hv-pi-amendment-link]")
			.off("click.hv-pi-amendment")
			.on("click.hv-pi-amendment", function (event) {
				event.preventDefault();
				const name = $(this).attr("data-hv-pi-amendment-link");
				if (name) frappe.set_route("Form", "Purchase Invoice", name);
			});
	}, 0);
}
