(function () {
	const HAUSVERWALTER_ROLES = ["Hausverwalter", "Hausverwalter (Buchung)"];
	const ADMIN_ROLES = ["System Manager"];
	const HIDDEN_FIELDS_BY_DOCTYPE = {
		Customer: ["tax_category", "tax_id", "tax_withholding_category"],
		"Sales Invoice": [
			"tax_id",
			"company_tax_id",
			"tax_category",
			"currency_and_price_list",
			"currency",
			"conversion_rate",
			"column_break2",
			"selling_price_list",
			"price_list_currency",
			"plc_conversion_rate",
			"ignore_pricing_rule",
			"taxes_section",
			"taxes_and_charges",
			"column_break_38",
			"shipping_rule",
			"column_break_55",
			"incoterm",
			"named_place",
			"section_break_40",
			"taxes",
			"section_break_43",
			"base_total_taxes_and_charges",
			"column_break_47",
			"total_taxes_and_charges",
			"sec_tax_breakup",
			"loyalty_points_redemption",
			"redeem_loyalty_points",
			"loyalty_points",
			"loyalty_amount",
			"column_break_77",
			"loyalty_program",
			"loyalty_redemption_account",
			"loyalty_redemption_cost_center",
			"sales_team_section_break",
			"sales_partner",
			"amount_eligible_for_commission",
			"column_break10",
			"commission_rate",
			"total_commission",
			"section_break2",
			"sales_team",
		],
		"Purchase Invoice": [
			"tax_id",
			"apply_tds",
			"tax_withholding_category",
			"tax_category",
			"taxes_section",
			"taxes_and_charges",
			"column_break_58",
			"shipping_rule",
			"column_break_49",
			"incoterm",
			"named_place",
			"section_break_51",
			"taxes",
			"base_taxes_and_charges_added",
			"base_taxes_and_charges_deducted",
			"base_total_taxes_and_charges",
			"column_break_40",
			"taxes_and_charges_added",
			"taxes_and_charges_deducted",
			"total_taxes_and_charges",
			"tax_withheld_vouchers_section",
			"tax_withheld_vouchers",
			"sec_tax_breakup",
		],
		"Payment Entry": [
			"paid_amount_after_tax",
			"base_paid_amount_after_tax",
			"received_amount_after_tax",
			"base_received_amount_after_tax",
			"taxes_and_charges_section",
			"purchase_taxes_and_charges_template",
			"sales_taxes_and_charges_template",
			"column_break_55",
			"apply_tax_withholding_amount",
			"tax_withholding_category",
			"section_break_56",
			"taxes",
			"section_break_60",
			"base_total_taxes_and_charges",
			"column_break_61",
			"total_taxes_and_charges",
			"deductions_or_loss_section",
			"deductions",
		],
		"Journal Entry": ["apply_tds", "tax_withholding_category"],
	};

	function getUserRoles() {
		return Array.isArray(frappe.user_roles) ? frappe.user_roles : [];
	}

	function shouldUseSimplifiedView() {
		const roles = getUserRoles();
		const isAdmin =
			frappe.session?.user === "Administrator" ||
			ADMIN_ROLES.some((role) => roles.includes(role));
		const isHausverwalter = HAUSVERWALTER_ROLES.some((role) => roles.includes(role));
		return isHausverwalter && !isAdmin;
	}

	function setFieldVisibility(frm, fieldname, visible) {
		const field = frm.get_field(fieldname);
		if (!field) return;

		if (typeof frm.toggle_display === "function") {
			frm.toggle_display(fieldname, visible);
			return;
		}

		frm.set_df_property(fieldname, "hidden", visible ? 0 : 1);
	}

	function apply(frm) {
		if (!frm || !frm.doctype) return;

		const fieldnames = HIDDEN_FIELDS_BY_DOCTYPE[frm.doctype] || [];
		if (!fieldnames.length) return;

		const visible = !shouldUseSimplifiedView();
		fieldnames.forEach((fieldname) => setFieldVisibility(frm, fieldname, visible));
	}

	window.hv_role_field_visibility = {
		apply,
		should_use_simplified_view: shouldUseSimplifiedView,
	};
})();
