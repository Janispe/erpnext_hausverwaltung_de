frappe.pages["hv-proposals"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("KI-Vorschläge · Synthetischer Pilot"), single_column: true });
	const root = $("<div class='p-4'>").appendTo(page.body);
	$("<p>").text(__("Nur synthetische Notizen. Ein Vorschlag ändert genau ein Label. Vorschau speichert keine Fachdaten. Jede Revision und jeder Vorgänger braucht eine eigene Freigabe und Ausführung.")).appendTo(root);
	const fields = $("<div>").appendTo(root);
	const control = (label, fieldname, fieldtype = "Data", options) => {
		const c = frappe.ui.form.make_control({ parent: fields, df: { label: __(label), fieldname, fieldtype, options }, render_input: true });
		return c;
	};
	const target = control("Synthetische Notiz", "target", "Link", "HV Synthetic Note");
	const label = control("Neues Label", "label");
	const pkg = control("Paket", "package");
	pkg.set_value("pilot");
	const dependencyText = $("<pre aria-label='Explizite Vorgänger'>").text("[]").appendTo(root);
	const buttons = $("<div class='mb-3 d-flex flex-wrap' style='gap:8px'>").appendTo(root);
	const status = $("<p role='status'>").appendTo(root);
	const diff = $("<div class='row'>").appendTo(root);
	const beforeBox = $("<section class='col-md-6'>").appendTo(diff);
	$("<h3>").text(__("Vorher (nach Vorgängern)")).appendTo(beforeBox);
	const before = $("<pre aria-label='Vorher'>").appendTo(beforeBox);
	const afterBox = $("<section class='col-md-6'>").appendTo(diff);
	$("<h3>").text(__("Nachher")).appendTo(afterBox);
	const after = $("<pre aria-label='Nachher'>").appendTo(afterBox);
	const detail = $("<pre aria-label='Preview-Grenzen und Abhängigkeiten'>").appendTo(root);
	const audit = $("<pre aria-label='Audit'>").appendTo(root);
	const list = $("<div aria-label='Vorschlagsliste'>").appendTo(root);
	let selected = null;
	let dependencies = [];
	let requestKey = crypto.randomUUID();
	const binding = (p) => ({ id: p.id, revision: p.revision, hash: p.hash });
	const showDependencies = () => dependencyText.text(JSON.stringify(dependencies, null, 2));
	const call = async (method, args = {}) => {
		const response = await frappe.call({ method: `hausverwaltung.proposals.frappe_service.${method}`, args, type: "POST", freeze: true });
		return response.message;
	};
	const render = (p) => {
		selected = p;
		const preview = p.current_preview || p.preview;
		status.text(`${p.id} · Revision ${p.revision} · ${p.hash} · ${p.status}`);
		before.text(JSON.stringify(preview.before, null, 2));
		after.text(JSON.stringify(preview.after, null, 2));
		detail.text(JSON.stringify({ real: preview.real, dependencies: preview.dependencies, effects: preview.effects, limits: preview.limits, conflicts: p.conflicts, result: p.result }, null, 2));
	};
	const load = async () => {
		list.empty();
		const proposals = await call("list_proposals");
		for (const p of proposals) {
			const row = $("<div class='mb-2'>").appendTo(list);
			$("<span>").text(`${p.target} · ${p.status} · r${p.revision} `).appendTo(row);
			$("<button class='btn btn-default btn-sm'>").text(__("Ansehen")).appendTo(row).on("click", async () => {
				const result = await call("view", { proposal_id: p.id });
				render(result);
				target.set_value(result.preview.target);
				label.set_value(result.preview.after.label);
				audit.text(JSON.stringify(await call("audit", { proposal_id: p.id }), null, 2));
			});
			$("<button class='btn btn-default btn-sm ml-2'>").text(__("Als Vorgänger auswählen")).appendTo(row).on("click", () => {
				dependencies = dependencies.filter((d) => d.id !== p.id);
				dependencies.push(binding(p));
				showDependencies();
			});
		}
	};
	const button = (title, fn) => $("<button class='btn btn-default'>").text(__(title)).appendTo(buttons).on("click", async () => {
		try { await fn(); } catch (e) { status.text(__("Aktion blockiert oder fehlgeschlagen; Servermeldung beachten.")); }
	});
	const requireSelected = () => { if (!selected) throw new Error("Select a proposal"); return binding(selected); };
	button("Vorschlag einreichen", async () => {
		render(await call("submit", { key: requestKey, package: pkg.get_value(), payload: { target: target.get_value(), label: label.get_value() }, dependencies }));
		requestKey = crypto.randomUUID();
		await load();
	});
	button("Neue Revision mit Preview", async () => {
		render(await call("revise", { binding: requireSelected(), payload: { target: target.get_value(), label: label.get_value() }, dependencies }));
		await load();
	});
	const roles = frappe.user_roles || [];
	if (roles.includes("HV Proposal Reviewer") && !roles.includes("HV Proposal Agent")) {
		for (const [title, approve] of [["Diese Revision freigeben", true], ["Diese Revision ablehnen", false]]) {
			button(title, async () => { render(await call("review", { binding: requireSelected(), approve })); await load(); });
		}
	}
	button("Genehmigte Revision ausführen", async () => { render(await call("execute", { binding: requireSelected() })); await load(); });
	button("Vorgängerauswahl leeren", async () => { dependencies = []; showDependencies(); });
	button("Aktualisieren", load);
	load();
};
