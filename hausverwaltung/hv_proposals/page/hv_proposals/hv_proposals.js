frappe.pages["hv-proposals"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("KI-Vorschläge · Synthetischer Pilot"), single_column: true });
	const root = $("<div class='p-4'>").appendTo(page.body);
	$("<p>").text(__("Unterstützte Aktion: Bezeichnung einer vorhandenen synthetischen Notiz ändern. Die Vorschau verändert die Notiz nicht. Jede Revision und jeder Vorgänger benötigt eine eigene Freigabe und Ausführung.")).appendTo(root);
	const fields = $("<div>").appendTo(root);
	const control = (label, fieldname, fieldtype = "Data", options) => {
		const c = frappe.ui.form.make_control({ parent: fields, df: { label: __(label), fieldname, fieldtype, options }, render_input: true });
		if (c.$input) c.$input.attr("aria-label", __(label));
		return c;
	};
	const target = control("Synthetische Notiz", "target", "Link", "HV Synthetic Note");
	const label = control("Neue Bezeichnung", "label");
	const pkg = control("Paket", "package");
	pkg.set_value("pilot");
	const dependencyText = $("<pre aria-label='Explizite Vorgänger'>").text("[]").appendTo(root);
	const buttons = $("<div class='mb-3 d-flex flex-wrap' style='gap:8px'>").appendTo(root);
	const status = $("<p role='status'>").appendTo(root);
	const diff = $("<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px'>").appendTo(root);
	const beforeBox = $("<section class='col-md-6'>").appendTo(diff);
	$("<h3>").text(__("Bezeichnung bisher")).appendTo(beforeBox);
	const before = $("<p aria-label='Vorher' style='font-size:18px;white-space:pre-wrap'>").appendTo(beforeBox);
	const afterBox = $("<section class='col-md-6'>").appendTo(diff);
	$("<h3>").text(__("Bezeichnung nach Ausführung")).appendTo(afterBox);
	const after = $("<p aria-label='Nachher' style='font-size:18px;white-space:pre-wrap'>").appendTo(afterBox);
	const resultText = $("<p aria-label='Ausführungsergebnis'>").appendTo(root);
	const technical = $("<details class='my-3'>").appendTo(root);
	$("<summary>").text(__("Technische Details, Abhängigkeiten und Grenzen")).appendTo(technical);
	const detail = $("<pre aria-label='Preview-Grenzen und Abhängigkeiten'>").appendTo(technical);
	$("<h3>").text(__("Prüf- und Ausführungsverlauf")).appendTo(root);
	const audit = $("<ul aria-label='Audit'>").appendTo(root);
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
		const states = { Pending: "Prüfung offen", Approved: "Freigegeben", Rejected: "Abgelehnt", Stale: "Veraltet", Succeeded: "Ausgeführt" };
		status.text(`Vorschlag ${p.id} · Revision ${p.revision} · ${states[p.status] || p.status}`);
		before.text(preview.before.label);
		after.text(preview.after.label);
		resultText.text(p.result ? `Ergebnis: Notiz ${p.result.id} wurde gespeichert. Bezeichnung: ${p.result.state.label}.` : "Noch keine Änderung an der Notiz ausgeführt.");
		detail.text(JSON.stringify({ revision_hash: p.hash, real: preview.real, dependencies: preview.dependencies, effects: preview.effects, limits: preview.limits, conflicts: p.conflicts, result: p.result }, null, 2));
	};
	const show = async (p) => {
		render(p);
		const events = await call("audit", { proposal_id: p.id });
		const titles = { Created: "Vorschlag eingereicht", Revised: "Neue Revision", Approved: "Revision freigegeben", Rejected: "Revision abgelehnt", Succeeded: "Änderung ausgeführt", ResultReused: "Gespeichertes Ergebnis erneut abgerufen", Stale: "Vorschau veraltet" };
		audit.empty();
		for (const event of events) $("<li>").text(`${titles[event.kind] || event.kind} · Revision ${event.number} · ${event.actor} · ${event.creation}`).appendTo(audit);
	};
	const load = async () => {
		list.empty();
		const proposals = await call("list_proposals");
		for (const p of proposals) {
			const row = $("<div class='mb-2'>").appendTo(list);
			$("<span>").text(`${p.target} · ${p.status} · r${p.revision} `).appendTo(row);
			$("<button class='btn btn-default btn-sm'>").text(__("Ansehen")).appendTo(row).on("click", async () => {
				selected = null;
				try {
					const result = await call("view", { proposal_id: p.id });
					target.set_value(result.preview.target);
					label.set_value(result.preview.after.label);
					pkg.set_value(result.package);
					dependencies = result.dependencies.map(({ id, revision, hash }) => ({ id, revision, hash }));
					showDependencies();
					await show(result);
				} catch (e) { status.text(__("Vorschlag konnte nicht geladen werden; Servermeldung beachten.")); }
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
	const metadata = () => ({ title: "Bezeichnung ändern", summary: label.get_value() });
	const requireSelected = () => { if (!selected) throw new Error("Select a proposal"); return binding(selected); };
	button("Vorschlag einreichen", async () => {
		await show(await call("submit", { key: requestKey, package: pkg.get_value(), package_meta: { title: pkg.get_value() }, metadata: metadata(), payload: { target: target.get_value(), label: label.get_value() }, dependencies }));
		requestKey = crypto.randomUUID();
		await load();
	});
	button("Neue Revision mit Preview", async () => {
		await show(await call("revise", { binding: requireSelected(), metadata: metadata(), payload: { target: target.get_value(), label: label.get_value() }, dependencies }));
		await load();
	});
	const roles = frappe.user_roles || [];
	if (roles.includes("HV Proposal Reviewer") && !roles.includes("HV Proposal Agent")) {
		for (const [title, approve] of [["Diese Revision freigeben", true], ["Diese Revision ablehnen", false]]) {
			button(title, async () => {
				if (!approve) {
					frappe.prompt([{ fieldname: "reason", fieldtype: "Small Text", label: __("Ablehnungsgrund"), reqd: 1 }], async ({ reason }) => {
						await show(await call("review", { binding: requireSelected(), approve, reason })); await load();
					}, __("Revision ablehnen"));
				} else { await show(await call("review", { binding: requireSelected(), approve })); await load(); }
			});
		}
	}
	button("Genehmigte Revision ausführen", async () => { await show(await call("execute", { binding: requireSelected() })); await load(); });
	button("Vorgängerauswahl leeren", async () => { dependencies = []; showDependencies(); });
	button("Aktualisieren", load);
	load();
};
