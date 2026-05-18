frappe.ui.form.on("Prozess Version", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		// Must match _LOCKED_SCALAR_FIELDS in prozess_version.py (+ Child-Tables)
		const locked_fields = [
			"version_key",
			"runtime_doctype",
			"titel",
			"beschreibung",
			"gueltig_ab",
			"gueltig_bis",
			"schritte",
			"schritt_kanten",
		];

		if (frm.doc.is_active) {
			// A2: aktive Version visuell sperren (Server-Lock in A1 ist source of truth)
			for (const fname of locked_fields) {
				frm.set_df_property(fname, "read_only", 1);
			}
			frm.dashboard.clear_headline();
			frm.dashboard.set_headline(
				__("Aktive Version — schreibgeschuetzt. Aenderungen erfordern eine neue Version."),
				"orange"
			);
			frm.add_custom_button(__("Bearbeiten als neue Version"), () => {
				_open_duplicate_dialog(frm);
			}).addClass("btn-primary");
		} else {
			// Felder editierbar lassen (defensiv falls jemand die Form vorher in aktivem
			// Zustand geoeffnet hatte und der Refresh nicht ganz frisch ist)
			for (const fname of locked_fields) {
				frm.set_df_property(fname, "read_only", 0);
			}
			frm.add_custom_button(__("Aktivieren"), () => _open_activation_dialog(frm));
		}

		frm.add_custom_button(__("Version duplizieren"), () => _open_duplicate_dialog(frm));

		_render_dag_preview(frm);
	},

	before_save(frm) {
		const errors = _validate_dag_locally(frm);
		if (errors.length) {
			frappe.validated = false;
			frappe.msgprint({
				title: __("DAG-Validierung fehlgeschlagen"),
				message: errors.map((e) => `<li>${frappe.utils.escape_html(e)}</li>`).join(""),
				indicator: "red",
				as_list: true,
			});
		}
	},
});

// A4 + B-min: Live-Refresh bei Edit der Schritte / Kanten
// Add/Remove sind Parent-Form-Events (Frappe-Konvention), Field-Changes sind Child-Events.
frappe.ui.form.on("Prozess Version", {
	schritte_add: (frm) => _render_dag_preview(frm),
	schritte_remove: (frm) => _render_dag_preview(frm),
	schritt_kanten_add: (frm) => _render_dag_preview(frm),
	schritt_kanten_remove: (frm) => _render_dag_preview(frm),
});

frappe.ui.form.on("Prozess Schritt", {
	titel: (frm) => _render_dag_preview(frm),
	step_key: (frm) => _render_dag_preview(frm),
});

frappe.ui.form.on("Prozess Schritt Kante", {
	step_key: (frm) => _render_dag_preview(frm),
	depends_on_step_key: (frm) => _render_dag_preview(frm),
});

function _open_duplicate_dialog(frm) {
	frappe.prompt(
		[
			{
				fieldname: "new_version_key",
				fieldtype: "Data",
				label: __("Neuer Version Key"),
				reqd: 1,
				default: (frm.doc.version_key || "") + "-v2",
			},
			{
				fieldname: "new_titel",
				fieldtype: "Data",
				label: __("Neuer Titel"),
				reqd: 1,
				default: frm.doc.titel,
			},
		],
		(values) => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.prozess_version.prozess_version.duplicate_version",
				args: {
					name: frm.doc.name,
					new_version_key: values.new_version_key,
					new_titel: values.new_titel,
				},
			}).then((r) => {
				if (r.message) frappe.set_route("Form", "Prozess Version", r.message);
			});
		},
		__("Version duplizieren"),
		__("Anlegen und oeffnen")
	);
}

function _open_activation_dialog(frm) {
	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.prozess_version.prozess_version.get_activation_preview",
		args: { name: frm.doc.name },
	}).then((r) => {
		const p = r.message || {};
		const replaces = p.currently_active
			? `<p>${__("Ersetzt aktuell aktive Version:")} <b>${frappe.utils.escape_html(p.currently_active.titel)}</b> (<code>${frappe.utils.escape_html(p.currently_active.version_key)}</code>)</p>`
			: `<p>${__("Aktuell ist keine Version fuer")} <b>${frappe.utils.escape_html(p.runtime_doctype || "")}</b> ${__("aktiv.")}</p>`;
		const html = `
			<h4>${frappe.utils.escape_html(p.version_titel || "")} <small class="text-muted">${frappe.utils.escape_html(p.version_key || "")}</small></h4>
			<p>${__("Schritte:")} <b>${p.schritt_count || 0}</b>, ${__("Abhaengigkeiten:")} <b>${p.kanten_count || 0}</b></p>
			${replaces}
			<p class="text-muted"><i>${__("Bestehende")} ${frappe.utils.escape_html(p.runtime_doctype || "")}${__("-Instanzen behalten ihre gespeicherte Prozess-Version und sind nicht betroffen.")}</i></p>
		`;
		frappe.confirm(html, () => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.prozess_version.prozess_version.activate_version",
				args: { name: frm.doc.name },
				freeze: true,
			}).then(() => frm.reload_doc());
		});
	});
}

function _validate_dag_locally(frm) {
	const schritte = frm.doc.schritte || [];
	const kanten = frm.doc.schritt_kanten || [];
	const step_keys = new Set(schritte.map((s) => (s.step_key || "").trim()).filter(Boolean));
	const errors = [];

	for (const k of kanten) {
		const sk = (k.step_key || "").trim();
		const dep = (k.depends_on_step_key || "").trim();
		if (sk && dep && sk === dep) {
			errors.push(__("Schritt kann nicht von sich selbst abhaengen: {0}", [sk]));
		}
	}
	for (const k of kanten) {
		const sk = (k.step_key || "").trim();
		const dep = (k.depends_on_step_key || "").trim();
		if (sk && !step_keys.has(sk)) errors.push(__("Kante referenziert unbekannten Schritt: {0}", [sk]));
		if (dep && !step_keys.has(dep)) errors.push(__("Kante referenziert unbekannten Vorgaenger-Schritt: {0}", [dep]));
	}
	const seen_edges = new Set();
	for (const k of kanten) {
		const sk = (k.step_key || "").trim();
		const dep = (k.depends_on_step_key || "").trim();
		if (!sk || !dep) continue;
		const key = sk + "\0" + dep;
		if (seen_edges.has(key)) errors.push(__("Doppelte Kante: {0} haengt mehrfach von {1} ab.", [sk, dep]));
		seen_edges.add(key);
	}

	// Cycle detection via DFS with coloring
	const adj = {};
	for (const sk of step_keys) adj[sk] = [];
	for (const k of kanten) {
		const sk = (k.step_key || "").trim();
		const dep = (k.depends_on_step_key || "").trim();
		if (sk && dep && step_keys.has(sk) && step_keys.has(dep)) {
			adj[sk].push(dep);
		}
	}
	const WHITE = 0, GRAY = 1, BLACK = 2;
	const color = {};
	for (const sk of step_keys) color[sk] = WHITE;
	let cycle_path = null;
	function dfs(node, path) {
		if (color[node] === GRAY) {
			cycle_path = path.slice(path.indexOf(node)).concat(node);
			return true;
		}
		if (color[node] === BLACK) return false;
		color[node] = GRAY;
		for (const nxt of adj[node] || []) {
			if (dfs(nxt, path.concat(node))) return true;
		}
		color[node] = BLACK;
		return false;
	}
	for (const sk of step_keys) {
		if (color[sk] === WHITE && dfs(sk, [])) {
			errors.push(__("Zyklus in Schritt-Abhaengigkeiten: {0}", [cycle_path.join(" -> ")]));
			break;
		}
	}

	return errors;
}

function _render_dag_preview(frm) {
	const field = frm.get_field("dag_preview_html");
	if (!field) return;
	const schritte = frm.doc.schritte || [];
	const kanten = frm.doc.schritt_kanten || [];
	if (!schritte.length) {
		field.$wrapper.html(`<p class="text-muted">${__("Noch keine Schritte definiert.")}</p>`);
		return;
	}
	const deps_by_step = {};
	for (const k of kanten) {
		const sk = (k.step_key || "").trim();
		const dep = (k.depends_on_step_key || "").trim();
		if (!sk || !dep) continue;
		deps_by_step[sk] = deps_by_step[sk] || [];
		deps_by_step[sk].push(dep);
	}
	const errors = _validate_dag_locally(frm);
	const errors_html = errors.length
		? `<div class="alert alert-danger"><b>${__("Probleme:")}</b><ul>${errors
				.map((e) => `<li>${frappe.utils.escape_html(e)}</li>`)
				.join("")}</ul></div>`
		: "";
	const rows = schritte
		.map((s) => {
			const sk = (s.step_key || "").trim();
			const titel = frappe.utils.escape_html(s.titel || sk);
			const deps = deps_by_step[sk] || [];
			const deps_html = deps.length
				? deps.map((d) => `<code>${frappe.utils.escape_html(d)}</code>`).join(", ")
				: `<i class="text-muted">${__("(keine Vorgaenger)")}</i>`;
			const pflicht = s.pflicht ? ` <span class="badge badge-warning">${__("Pflicht")}</span>` : "";
			return `<tr>
				<td><code>${frappe.utils.escape_html(sk)}</code></td>
				<td>${titel}${pflicht}</td>
				<td>${deps_html}</td>
			</tr>`;
		})
		.join("");
	field.$wrapper.html(`
		${errors_html}
		<div class="dag-graph-container" style="margin: 8px 0 12px 0;"></div>
		<table class="table table-condensed table-bordered" style="margin-top:8px;">
			<thead><tr><th>${__("Step-Key")}</th><th>${__("Titel")}</th><th>${__("Haengt ab von")}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table>
	`);

	// Mermaid-Graph oberhalb der Tabelle (lazy via frappe.require)
	const nodes = schritte
		.map((s) => ({
			step_key: (s.step_key || "").trim(),
			titel: s.titel || s.step_key,
			pflicht: !!s.pflicht,
		}))
		.filter((n) => n.step_key);
	const edges = kanten
		.map((k) => ({
			from: (k.depends_on_step_key || "").trim(),
			to: (k.step_key || "").trim(),
		}))
		.filter((e) => e.from && e.to);
	frappe.require("/assets/hausverwaltung/js/dag_mermaid.js", () => {
		const container = field.$wrapper.find(".dag-graph-container").get(0);
		if (!container) return;
		window.hausverwaltung.dag.renderDag({ container, nodes, edges });
	});
}
