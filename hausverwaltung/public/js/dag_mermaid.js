// hausverwaltung.dag — DAG-Visualisierung via Mermaid
//
// Mermaid: gepinnt auf v10.9.3, MIT License
// Source: https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js
// Bundle: hausverwaltung/public/js/lib/mermaid.min.js (~3.2 MB, ~530 KB gzipped)
//
// Sicherheits-Annahmen:
//  - securityLevel: "strict" (Labels koennen UI-pflegbar sein → XSS-Schutz)
//  - Node-IDs werden NIE direkt aus step_key gebaut (Mermaid-Reserved-Words wie end/class/subgraph)
//  - Click-Handler werden ueber eine safeId→step_key-Map gebunden, nicht via Regex auf DOM-IDs

(function () {
	window.hausverwaltung = window.hausverwaltung || {};
	const ns = (window.hausverwaltung.dag = window.hausverwaltung.dag || {});
	let _loaded = false;

	async function _ensureMermaid() {
		if (_loaded && window.mermaid) return window.mermaid;
		await new Promise((resolve) =>
			frappe.require("/assets/hausverwaltung/js/lib/mermaid.min.js", resolve)
		);
		window.mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "strict" });
		_loaded = true;
		return window.mermaid;
	}

	function _safeId(step_key, index) {
		const cleaned = String(step_key || "").replace(/[^a-zA-Z0-9_]/g, "_");
		return `n_${cleaned || "x"}_${index}`;
	}

	function _normLabel(s) {
		return String(s || "")
			.replace(/[\r\n]+/g, " ")
			.replace(/[\[\]]/g, "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");
	}

	function _buildSource({ nodes, edges, status_by_step }, idMap) {
		const lines = ["flowchart TD"];
		lines.push("classDef done fill:#28a745,stroke:#1e7e34,color:#fff");
		lines.push("classDef locked fill:#adb5bd,stroke:#6c757d,color:#fff,opacity:0.55");
		lines.push("classDef wip fill:#ffc107,stroke:#d39e00,color:#000");
		lines.push("classDef open fill:#17a2b8,stroke:#117a8b,color:#fff");
		lines.push("classDef pflicht stroke-width:3px");

		nodes.forEach((n, i) => {
			const sid = _safeId(n.step_key, i);
			idMap.safeToStep[sid] = n.step_key;
			idMap.stepToSafe[n.step_key] = sid;
			lines.push(`${sid}["${_normLabel(n.titel || n.step_key)}"]`);
		});
		for (const e of edges) {
			const from = idMap.stepToSafe[e.from];
			const to = idMap.stepToSafe[e.to];
			if (from && to) lines.push(`${from} --> ${to}`);
		}
		if (status_by_step) {
			for (const n of nodes) {
				const klass = status_by_step[n.step_key] || "open";
				const sid = idMap.stepToSafe[n.step_key];
				if (sid) lines.push(`class ${sid} ${klass}`);
			}
		}
		for (const n of nodes) {
			const sid = idMap.stepToSafe[n.step_key];
			if (n.pflicht && sid) lines.push(`class ${sid} pflicht`);
		}
		return lines.join("\n");
	}

	ns.renderDag = async function ({ container, nodes, edges, status_by_step, on_click }) {
		if (!container) return;
		await _ensureMermaid();
		// Render-Token gegen Async-Race: bei schnellen Live-Refreshes kann ein aelterer
		// Render spaeter zurueckkommen und den neuen Graph ueberschreiben. Token wird
		// pro Container hochgezaehlt, nach await render() verglichen.
		const token = (container.__hv_render_token = (container.__hv_render_token || 0) + 1);

		const idMap = { safeToStep: {}, stepToSafe: {} };
		const source = _buildSource({ nodes, edges, status_by_step }, idMap);
		const renderId = "hv-dag-" + Math.random().toString(36).slice(2, 8);

		let svg;
		try {
			const result = await window.mermaid.render(renderId, source);
			svg = result.svg;
		} catch (err) {
			if (container.__hv_render_token !== token) return;
			$(container).html(
				`<p class="text-danger">${__("Graph konnte nicht gerendert werden.")}</p>`
			);
			console.error("hausverwaltung.dag.renderDag failed", err);
			return;
		}

		if (container.__hv_render_token !== token) return;
		$(container).empty().html(svg);

		if (on_click) {
			for (const [safeId, originalKey] of Object.entries(idMap.safeToStep)) {
				$(container)
					.find(`g.node[id^="flowchart-${safeId}-"]`)
					.css("cursor", "pointer")
					.on("click", () => on_click(originalKey));
			}
		}
	};
})();
