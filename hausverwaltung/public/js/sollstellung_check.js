// Renderer für die Sollstellungs-Prüfung (siehe scripts/check_mietrechnungen.py).
// Wird via frappe.require() in mietrechnungen_durchlauf.js und mietvertrag.js
// nachgeladen.
//
//   hausverwaltung.sollstellung_check.show_durchlauf(payload)
//   hausverwaltung.sollstellung_check.show_mietvertrag(payload, opts)

(function () {
	const esc = frappe.utils.escape_html;

	function fmt_money(v) {
		if (v === null || v === undefined || v === "") return "";
		const n = Number(v);
		if (Number.isNaN(n)) return esc(String(v));
		return n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
	}

	function si_link(name) {
		if (!name) return "";
		return `<a href="/app/sales-invoice/${encodeURIComponent(name)}" target="_blank">${esc(name)}</a>`;
	}

	function mv_link(name) {
		if (!name) return "";
		return `<a href="/app/mietvertrag/${encodeURIComponent(name)}" target="_blank">${esc(name)}</a>`;
	}

	function whg_link(name) {
		if (!name) return "";
		return `<a href="/app/wohnung/${encodeURIComponent(name)}" target="_blank">${esc(name)}</a>`;
	}

	function render_fehlend(rows) {
		if (!rows || !rows.length) return "";
		const trs = rows
			.map((r) => {
				const hint = r.hinweis ? `<br><small class="text-muted">${esc(r.hinweis)}</small>` : "";
				return `<tr>
					<td>${mv_link(r.mietvertrag)}</td>
					<td>${whg_link(r.wohnung)}</td>
					<td>${esc(r.typ)}</td>
					<td class="text-right">${fmt_money(r.erwartet_betrag)}${hint}</td>
				</tr>`;
			})
			.join("");
		return `<div class="mt-3">
			<h5 style="color:#c0392b">🚫 ${__("Fehlende Sollstellungen")} (${rows.length})</h5>
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th>${__("Mietvertrag")}</th>
					<th>${__("Wohnung")}</th>
					<th>${__("Typ")}</th>
					<th class="text-right">${__("Erwarteter Betrag")}</th>
				</tr></thead>
				<tbody>${trs}</tbody>
			</table>
		</div>`;
	}

	function render_ueberfluessig(rows) {
		if (!rows || !rows.length) return "";
		const trs = rows
			.map(
				(r) => `<tr>
				<td>${mv_link(r.mietvertrag)}</td>
				<td>${whg_link(r.wohnung)}</td>
				<td>${esc(r.typ)}</td>
				<td>${si_link(r.sales_invoice)}</td>
				<td class="text-right">${fmt_money(r.aktuell_betrag)}</td>
			</tr>`
			)
			.join("");
		return `<div class="mt-3">
			<h5 style="color:#d35400">⚠️ ${__("Überflüssige Rechnungen")} (${rows.length})</h5>
			<p class="text-muted small">${__(
				"Vertrag sieht für diesen Typ aktuell 0 € vor, aber eine Sales Invoice existiert."
			)}</p>
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th>${__("Mietvertrag")}</th>
					<th>${__("Wohnung")}</th>
					<th>${__("Typ")}</th>
					<th>${__("Sales Invoice")}</th>
					<th class="text-right">${__("Aktueller Betrag")}</th>
				</tr></thead>
				<tbody>${trs}</tbody>
			</table>
		</div>`;
	}

	function render_abweichungen(rows) {
		if (!rows || !rows.length) return "";
		const trs = rows
			.map((r) => {
				const erwartet = r.feld === "betrag" ? fmt_money(r.erwartet) : esc(String(r.erwartet ?? ""));
				const aktuell = r.feld === "betrag" ? fmt_money(r.aktuell) : esc(String(r.aktuell ?? ""));
				return `<tr>
					<td>${si_link(r.sales_invoice)}</td>
					<td>${mv_link(r.mietvertrag)}</td>
					<td>${esc(r.typ)}</td>
					<td><code>${esc(r.feld)}</code></td>
					<td>${erwartet}</td>
					<td>${aktuell}</td>
				</tr>`;
			})
			.join("");
		return `<div class="mt-3">
			<h5 style="color:#2980b9">🔧 ${__("Abweichungen")} (${rows.length})</h5>
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th>${__("Sales Invoice")}</th>
					<th>${__("Mietvertrag")}</th>
					<th>${__("Typ")}</th>
					<th>${__("Feld")}</th>
					<th>${__("Erwartet")}</th>
					<th>${__("Aktuell")}</th>
				</tr></thead>
				<tbody>${trs}</tbody>
			</table>
		</div>`;
	}

	function render_sections(payload) {
		const has_problems =
			(payload.fehlend && payload.fehlend.length) ||
			(payload.ueberfluessig && payload.ueberfluessig.length) ||
			(payload.abweichungen && payload.abweichungen.length);
		if (!has_problems) {
			const ok_count = payload.ok_count || 0;
			return `<div class="alert alert-success">✅ ${__(
				"Alle Sollstellungen vollständig & korrekt — {0} Positionen geprüft.",
				[ok_count]
			)}</div>`;
		}
		return [
			render_fehlend(payload.fehlend || []),
			render_ueberfluessig(payload.ueberfluessig || []),
			render_abweichungen(payload.abweichungen || []),
		].join("");
	}

	function show_durchlauf(payload) {
		const body = render_sections(payload);
		const dlg = new frappe.ui.Dialog({
			title: __("Sollstellungs-Prüfung — {0}", [esc(payload.monat || "")]),
			size: "large",
		});
		dlg.$body.html(body);
		dlg.show();
	}

	function show_mietvertrag(payload, opts) {
		const monate = payload.monate || [];
		let body = "";
		if (!monate.length) {
			body = `<div class="alert alert-success">✅ ${__(
				"Keine Abweichungen für diesen Mietvertrag gefunden."
			)}</div>`;
		} else {
			const summary = `<p class="text-muted">${__(
				"Gefunden: {0} Monate mit Befunden.",
				[monate.length]
			)}</p>`;
			const blocks = monate
				.map(
					(m) => `<div class="card mt-3" style="padding:10px;border:1px solid #e0e0e0;border-radius:4px">
				<h4>${esc(m.monat)}</h4>
				${render_sections(m)}
			</div>`
				)
				.join("");
			body = summary + blocks;
		}
		const dlg = new frappe.ui.Dialog({
			title: __("Sollstellungs-Prüfung — {0}", [esc((opts && opts.title_suffix) || payload.mietvertrag || "")]),
			size: "extra-large",
		});
		dlg.$body.html(body);
		dlg.show();
	}

	window.hausverwaltung = window.hausverwaltung || {};
	window.hausverwaltung.sollstellung_check = {
		show_durchlauf,
		show_mietvertrag,
		render_sections,
	};
})();
