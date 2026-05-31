frappe.ui.form.on("Dunning", {
	setup(frm) {
		frm.set_query("hv_serienbrief_vorlage", () => ({
			filters: {
				haupt_verteil_objekt: ["in", ["", "Dunning"]],
			},
		}));
	},

	onload(frm) {
		remember_auto_template(frm);
	},

	refresh(frm) {
		apply_hv_dunning_labels(frm);
		remember_auto_template(frm);
		toggle_standard_letter_fields(frm);
		guard_dunning_payment_button(frm);
		add_fee_invoice_action(frm);
		add_template_actions(frm);
		render_pdf_preview(frm);
	},

	dunning_type(frm) {
		set_template_from_dunning_type(frm);
	},

	hv_serienbrief_vorlage(frm) {
		toggle_standard_letter_fields(frm);
	},
});

function apply_hv_dunning_labels(frm) {
	frm.set_df_property("dunning_type", "label", __("Mahnstufe / Regel"));
	frm.set_df_property(
		"dunning_type",
		"description",
		__(
			"Optionale Regel für Mahngebühr, Verzugszins, Variablenwerte und Default-Vorlage."
		)
	);
	frm.set_df_property("hv_serienbrief_vorlage", "label", __("Serienbrief Vorlage"));
	frm.set_df_property(
		"hv_serienbrief_vorlage",
		"description",
		__(
			"Briefvorlage, die beim Drucken dieser Mahnung gerendert wird. Diese Auswahl überschreibt den Default der Mahnstufe."
		)
	);
	frm.set_df_property("hv_serienbrief_werte", "label", __("Serienbrief-Werte für diese Mahnung"));
	frm.set_df_property(
		"hv_serienbrief_werte",
		"description",
		__(
			"Optionale Variablenwerte nur für diese konkrete Mahnung. Gleichnamige Werte überschreiben die Defaults aus der Mahnstufe."
		)
	);
}

function toggle_standard_letter_fields(frm) {
	const use_serienbrief = Boolean(frm.doc.hv_serienbrief_vorlage);
	frm.toggle_display(["body_text", "closing_text"], !use_serienbrief);
}

function add_template_actions(frm) {
	if (!frm.doc.hv_serienbrief_vorlage) return;

	frm.add_custom_button(__("Serienbrief Vorlage öffnen"), () => {
		frappe.set_route("Form", "Serienbrief Vorlage", frm.doc.hv_serienbrief_vorlage);
	});
}

function add_fee_invoice_action(frm) {
	if (!frm.doc.hv_dunning_fee_sales_invoice) return;

	frm.add_custom_button(__("Mahngebühr-Rechnung öffnen"), () => {
		frappe.set_route("Form", "Sales Invoice", frm.doc.hv_dunning_fee_sales_invoice);
	});
}

function guard_dunning_payment_button(frm) {
	const message = __(
		"Bitte Zahlung gegen die offenen Sales Invoices buchen. Die Mahnung ist nur Brief und Mahnhistorie."
	);

	if (frm.events) {
		frm.events.make_payment_entry = () => {
			frappe.msgprint({
				title: __("Zahlung über Rechnung buchen"),
				message,
				indicator: "orange",
			});
		};
	}

	const remove_payment_button = () => {
		if (frm.remove_custom_button) {
			frm.remove_custom_button(__("Payment"), __("Create"));
		}
	};
	remove_payment_button();
	setTimeout(remove_payment_button, 0);
	setTimeout(remove_payment_button, 250);
}

function render_pdf_preview(frm) {
	ensure_pdf_preview_styles();

	let host = frm.$wrapper.find(".hv-dunning-pdf-preview-host");
	if (!host.length) {
		host = $('<div class="hv-dunning-pdf-preview-host"></div>');
		const dashboard = frm.$wrapper.find(".form-dashboard").first();
		if (dashboard.length) {
			dashboard.after(host);
		} else {
			frm.$wrapper.find(".form-layout").first().prepend(host);
		}
	}

	if (frm.is_new()) {
		host.html(`
			<div class="hv-dunning-pdf-preview">
				<div class="hv-dunning-pdf-preview-head">
					<div>
						<div class="hv-dunning-pdf-preview-title">${__("PDF-Vorschau")}</div>
						<div class="hv-dunning-pdf-preview-subtitle">${__(
							"Speichern Sie die Mahnung, um das finale PDF hier zu rendern."
						)}</div>
					</div>
				</div>
			</div>
		`);
		return;
	}

	const pdf_url = build_dunning_pdf_url(frm);
	const subtitle = frm.is_dirty()
		? __("Ungespeicherte Änderungen sind noch nicht im PDF. Speichern Sie die Mahnung und laden Sie die Vorschau neu.")
		: __("Gerendert über denselben PDF-Endpunkt wie der spätere Ausdruck.");
	host.html(`
		<div class="hv-dunning-pdf-preview">
			<div class="hv-dunning-pdf-preview-head">
				<div>
					<div class="hv-dunning-pdf-preview-title">${__("PDF-Vorschau")}</div>
					<div class="hv-dunning-pdf-preview-subtitle">${subtitle}</div>
				</div>
				<div class="hv-dunning-pdf-preview-actions">
					<button class="btn btn-xs btn-default hv-dunning-pdf-reload" type="button">
						${__("Neu laden")}
					</button>
					<button class="btn btn-xs btn-default hv-dunning-pdf-open" type="button">
						${__("Öffnen")}
					</button>
				</div>
			</div>
			<iframe class="hv-dunning-pdf-frame" src="${pdf_url}" title="${__("PDF-Vorschau")}"></iframe>
		</div>
	`);

	host.find(".hv-dunning-pdf-reload").on("click", () => {
		host.find(".hv-dunning-pdf-frame").attr("src", build_dunning_pdf_url(frm));
	});
	host.find(".hv-dunning-pdf-open").on("click", () => {
		window.open(build_dunning_pdf_url(frm), "_blank");
	});
}

function build_dunning_pdf_url(frm) {
	const params = new URLSearchParams({
		doctype: frm.doctype,
		name: frm.doc.name,
		no_letterhead: "0",
		_: String(Date.now()),
	});
	return `/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`;
}

function ensure_pdf_preview_styles() {
	if (document.getElementById("hv-dunning-pdf-preview-style")) return;

	$(`<style id="hv-dunning-pdf-preview-style">
		.hv-dunning-pdf-preview {
			margin: 0 0 16px;
			border: 1px solid var(--border-color);
			border-radius: 6px;
			background: var(--fg-color);
			overflow: hidden;
		}
		.hv-dunning-pdf-preview-head {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 12px;
			padding: 10px 12px;
			border-bottom: 1px solid var(--border-color);
			background: var(--subtle-fg);
		}
		.hv-dunning-pdf-preview-title {
			font-size: 13px;
			font-weight: 600;
			color: var(--text-color);
		}
		.hv-dunning-pdf-preview-subtitle {
			margin-top: 2px;
			font-size: 12px;
			color: var(--text-muted);
		}
		.hv-dunning-pdf-preview-actions {
			display: flex;
			flex: 0 0 auto;
			gap: 6px;
		}
		.hv-dunning-pdf-frame {
			display: block;
			width: 100%;
			height: 72vh;
			min-height: 520px;
			border: 0;
			background: #fff;
		}
		@media (max-width: 767px) {
			.hv-dunning-pdf-preview-head {
				align-items: flex-start;
				flex-direction: column;
			}
			.hv-dunning-pdf-frame {
				height: 70vh;
				min-height: 420px;
			}
		}
	</style>`).appendTo(document.head);
}

function remember_auto_template(frm) {
	if (!frm.doc.dunning_type || !frm.doc.hv_serienbrief_vorlage) {
		frm.__hv_last_auto_template = null;
		return;
	}

	frappe.db
		.get_value("Dunning Type", frm.doc.dunning_type, "hv_serienbrief_vorlage")
		.then((r) => {
			const template = r?.message?.hv_serienbrief_vorlage || "";
			frm.__hv_last_auto_template =
				template && template === frm.doc.hv_serienbrief_vorlage ? template : null;
		});
}

function set_template_from_dunning_type(frm) {
	if (!frm.doc.dunning_type) return;

	const current = frm.doc.hv_serienbrief_vorlage || "";
	const may_replace = !current || current === frm.__hv_last_auto_template;
	if (!may_replace) return;

	frappe.db
		.get_value("Dunning Type", frm.doc.dunning_type, "hv_serienbrief_vorlage")
		.then((r) => {
			const template = r?.message?.hv_serienbrief_vorlage || "";
			if (!template) return;

			frm.__hv_last_auto_template = template;
			frm.set_value("hv_serienbrief_vorlage", template);
		});
}
