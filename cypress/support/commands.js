// ── Authentication ──────────────────────────────────────────────

Cypress.Commands.add("login", (user, password) => {
	if (!user) user = Cypress.env("hv_user") || "hv";
	if (!password) password = Cypress.env("hv_password") || "hv";

	cy.session([user, password], () => {
		cy.request({
			url: "/api/method/login",
			method: "POST",
			body: { usr: user, pwd: password },
		});
	});
});

// ── Frappe API helpers ─────────────────────────────────────────

Cypress.Commands.add("call", (method, args) => {
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf_token) => {
			return cy
				.request({
					url: `/api/method/${method}`,
					method: "POST",
					body: args,
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
				})
				.then((res) => {
					expect(res.status).eq(200);
					return res.body;
				});
		});
});

Cypress.Commands.add("insert_doc", (doctype, args, ignore_duplicate) => {
	if (!args.doctype) args.doctype = doctype;
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf_token) => {
			return cy
				.request({
					method: "POST",
					url: `/api/resource/${doctype}`,
					body: args,
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
					failOnStatusCode: !ignore_duplicate,
				})
				.then((res) => {
					if (ignore_duplicate) {
						expect(res.status).to.be.oneOf([200, 409]);
					} else {
						expect(res.status).eq(200);
					}
					return res.body.data;
				});
		});
});

Cypress.Commands.add("remove_doc", (doctype, name) => {
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf_token) => {
			return cy.request({
				method: "DELETE",
				url: `/api/resource/${doctype}/${name}`,
				headers: {
					Accept: "application/json",
					"X-Frappe-CSRF-Token": csrf_token,
				},
				failOnStatusCode: false,
			});
		});
});

Cypress.Commands.add("get_list", (doctype, fields = [], filters = []) => {
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf_token) => {
			return cy
				.request({
					method: "GET",
					url: `/api/resource/${doctype}?fields=${JSON.stringify(fields)}&filters=${JSON.stringify(filters)}`,
					headers: {
						Accept: "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
				})
				.then((res) => {
					expect(res.status).eq(200);
					return res.body;
				});
		});
});

// ── Navigation ─────────────────────────────────────────────────

Cypress.Commands.add("go_to_list", (doctype) => {
	const route = doctype.toLowerCase().replace(/ /g, "-");
	cy.visit(`/app/${route}`);
	cy.get(".frappe-list", { timeout: 30000 }).should("exist");
});

Cypress.Commands.add("new_form", (doctype) => {
	const route = doctype.toLowerCase().replace(/ /g, "-");
	cy.visit(`/app/${route}/new`);
	cy.window({ timeout: 30000 }).its("cur_frm").should("exist");
});

Cypress.Commands.add("open_doc", (doctype, name) => {
	const route = doctype.toLowerCase().replace(/ /g, "-");
	cy.visit(`/app/${route}/${encodeURIComponent(name)}`);
	cy.window({ timeout: 30000 }).its("cur_frm").should("exist");
});

// ── Form helpers ───────────────────────────────────────────────

Cypress.Commands.add("get_field", (fieldname, fieldtype = "Data") => {
	const el = fieldtype === "Select" ? "select" : "input";
	let selector = `[data-fieldname="${fieldname}"] ${el}:visible`;
	if (fieldtype === "Text Editor") {
		selector = `[data-fieldname="${fieldname}"] .ql-editor[contenteditable=true]:visible`;
	}
	return cy.get(selector).first();
});

Cypress.Commands.add("fill_field", (fieldname, value, fieldtype = "Data") => {
	cy.get_field(fieldname, fieldtype).as("input");
	if (fieldtype === "Select") {
		cy.get("@input").select(value);
	} else {
		cy.get("@input").type(value, {
			waitForAnimations: false,
			parseSpecialCharSequences: false,
			force: true,
			delay: 100,
		});
	}
	return cy.get("@input");
});

Cypress.Commands.add("save", () => {
	cy.intercept("/api/method/frappe.desk.form.save.savedocs").as("save_call");
	cy.window().then((win) => {
		win.cur_frm.save();
	});
	cy.wait("@save_call", { timeout: 60000 });
});

// ── Dialog helpers ─────────────────────────────────────────────

Cypress.Commands.add("get_open_dialog", () => {
	return cy.get(".modal:visible").last();
});

Cypress.Commands.add("click_modal_primary_button", (btn_name) => {
	cy.get(".modal-footer > .standard-actions > .btn-primary")
		.contains(btn_name)
		.click({ force: true });
});

// ── Custom: MultiSelectDialog helpers ──────────────────────────

Cypress.Commands.add("get_multiselect_dialog", () => {
	return cy.get(".modal:visible .frappe-list").closest(".modal");
});

Cypress.Commands.add("multiselect_check_setter", (fieldname) => {
	return cy
		.get_multiselect_dialog()
		.find(`[data-fieldname="${fieldname}"]`)
		.should("exist");
});

// ── Existence helpers (für defensive Skips) ────────────────────

Cypress.Commands.add("first_doc_name", (doctype, filters = []) => {
	return cy.get_list(doctype, ["name"], filters).then((r) => {
		const data = r.data || [];
		return data.length > 0 ? data[0].name : null;
	});
});

// ── Custom Button Helper ───────────────────────────────────────

Cypress.Commands.add("click_custom_button", (group, label) => {
	cy.get(".page-container:visible .inner-group-button .btn")
		.contains(group)
		.click({ force: true });
	cy.get(".page-container:visible .inner-group-button .dropdown-menu:visible a")
		.contains(label)
		.click({ force: true });
});

// ── API Helper für Permission-Tests ────────────────────────────

Cypress.Commands.add("api_post", (method, body = {}, opts = {}) => {
	return cy.window().then((win) => {
		const csrf_token = (win.frappe && win.frappe.csrf_token) || "token";
		return cy.request({
			method: "POST",
			url: `/api/method/${method}`,
			body,
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrf_token,
			},
			failOnStatusCode: false,
			...opts,
		});
	});
});
