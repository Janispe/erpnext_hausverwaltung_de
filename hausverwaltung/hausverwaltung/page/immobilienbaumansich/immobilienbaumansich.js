frappe.pages["immobilienbaumansich"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Immobilien",
		single_column: true,
	});

	// Tabelle erstellen
	const table = $(
		`<table class="table table-bordered">
<thead>
<tr>
<th>Immobilie</th>
<th>Gebäudeteil</th>
<th>Wohnung</th>
<th>Mieter</th>
<th>Telefon</th>
</tr>
</thead>
<tbody></tbody>
</table>`
	).appendTo(page.body);
	const filterBar = $(
		`<tr class="hv-immobilien-filter">
<th><input type="text" class="form-control input-sm hv-filter" data-filter="immo" placeholder="Immobilie"></th>
<th><input type="text" class="form-control input-sm hv-filter" data-filter="teil" placeholder="Gebäudeteil"></th>
<th><input type="text" class="form-control input-sm hv-filter" data-filter="wohnung" placeholder="Wohnung"></th>
<th><input type="text" class="form-control input-sm hv-filter" data-filter="mieter" placeholder="Mieter"></th>
<th><input type="text" class="form-control input-sm hv-filter" data-filter="telefon" placeholder="Telefon"></th>
</tr>`
	);
	table.find("thead").append(filterBar);
	let tbody = null;
	const normalizeFilter = (value) => (value || "").toString().toLowerCase().trim();
	const getFilterValues = () => {
		const values = {};
		filterBar.find(".hv-filter").each(function () {
			values[$(this).data("filter")] = normalizeFilter($(this).val());
		});
		return values;
	};
	const applyFilters = () => {
		if (!tbody) {
			return;
		}
		const filters = getFilterValues();
		const hasFilters = Object.values(filters).some((v) => v);
		const immoRows = tbody.find("tr.immo-row");
		const teilRows = tbody.find("tr.teil-row");
		const wohnungRows = tbody.find("tr.wohnung-row");

		if (!hasFilters) {
			immoRows.show().find(".toggle-icon").text("▶");
			teilRows.hide().find(".toggle-icon").text("▶");
			wohnungRows.hide();
			return;
		}

		wohnungRows.each(function () {
			const row = $(this);
			const immoIdx = row.data("immo-idx");
			const teilIdx = row.data("teil-idx");
			const immoRow = immoRows.filter(`[data-immo-idx='${immoIdx}']`);
			const teilRow = teilRows.filter(
				`[data-immo-idx='${immoIdx}'][data-teil-idx='${teilIdx}']`
			);
			const immoLabel = normalizeFilter(immoRow.find(".immo-link").text());
			const teilLabel = normalizeFilter(
				teilRow.clone().find(".toggle-icon").remove().end().text()
			);
			const cells = row.children("td");
			const wohnungLabel = normalizeFilter(cells.eq(2).text());
			const mieterLabel = normalizeFilter(cells.eq(3).text());
			const telefonLabel = normalizeFilter(cells.eq(4).text());
			const matches =
				(!filters.immo || immoLabel.includes(filters.immo)) &&
				(!filters.teil || teilLabel.includes(filters.teil)) &&
				(!filters.wohnung || wohnungLabel.includes(filters.wohnung)) &&
				(!filters.mieter || mieterLabel.includes(filters.mieter)) &&
				(!filters.telefon || telefonLabel.includes(filters.telefon));
			row.toggle(matches);
		});

		teilRows.each(function () {
			const row = $(this);
			const immoIdx = row.data("immo-idx");
			const teilIdx = row.data("teil-idx");
			const visibleChildren = wohnungRows.filter(
				`[data-immo-idx='${immoIdx}'][data-teil-idx='${teilIdx}']:visible`
			);
			const shouldShow = visibleChildren.length > 0;
			row.toggle(shouldShow);
			row.find(".toggle-icon").text(shouldShow ? "▼" : "▶");
		});

		immoRows.each(function () {
			const row = $(this);
			const immoIdx = row.data("immo-idx");
			const visibleChildren = teilRows.filter(`[data-immo-idx='${immoIdx}']:visible`);
			const shouldShow = visibleChildren.length > 0;
			row.toggle(shouldShow);
			row.find(".toggle-icon").text(shouldShow ? "▼" : "▶");
		});
	};
	filterBar.on("input", ".hv-filter", applyFilters);

	// Daten abrufen
	frappe.call({
		method: "hausverwaltung.hausverwaltung.page.immobilienbaumansich.immobilienbaumansich.get_tree_data",
		callback: function (r) {
			if (!r.message) {
				return;
			}

			tbody = table.find("tbody");
			r.message.forEach((immo, immoIdx) => {
				const immoRow = $(
					`<tr class="immo-row" data-immo-idx="${immoIdx}" style="cursor:pointer;">
<td colspan="5">
<span class="toggle-icon">▶</span>
<a href="#" class="immo-link" data-immo="${immo.name}">${immo.label || immo.name}</a>
</td>
</tr>`
				);
				tbody.append(immoRow);

				// Click-Handler für Immobilie-Link
				immoRow.find(".immo-link").on("click", function(e) {
					e.preventDefault();
					e.stopPropagation();
					frappe.set_route("Form", "Immobilie", immo.name);
				});

				(immo.teile || []).forEach((teil, teilIdx) => {
					const teilRow = $(
						`<tr class="teil-row" data-immo-idx="${immoIdx}" data-teil-idx="${teilIdx}" style="display:none; cursor:pointer;">
<td></td>
<td colspan="4">
<span class="toggle-icon">▶</span>
${teil.name || ""}
</td>
</tr>`
					);
					tbody.append(teilRow);

					const groupRest = (value) => value.replace(/(\d{3})(?=\d)/g, "$1 ");
					const formatTelefonToken = (token) => {
						const cleaned = token.replace(/[^\d+]/g, "");
						const hasPlus = cleaned.startsWith("+");
						const digits = cleaned.replace(/\D/g, "");
						if (!digits) {
							return token;
						}
						if (!hasPlus) {
							return groupRest(digits);
						}

						let countryLen = 2;
						if (digits.startsWith("1")) {
							countryLen = 1;
						}
						const country = digits.slice(0, countryLen);
						const rest = digits.slice(countryLen);
						let areaLen = 2;
						if (country === "49" && rest.startsWith("1")) {
							areaLen = 3;
						}
						const area = rest.slice(0, Math.min(areaLen, rest.length));
						const subscriber = rest.slice(area.length);
						const grouped = groupRest(subscriber);
						const paddedArea = area ? area.padEnd(3, " ") : "";
						return `+${country}${paddedArea ? ` ${paddedArea}` : ""}${grouped ? ` ${grouped}` : ""}`;
					};
					const formatTelefonLine = (line) =>
						line.replace(/(\+?\d{5,})/g, (match) => formatTelefonToken(match));
					const formatTelefon = (raw) =>
						(raw || "")
							.split(/\r?\n/)
							.map((line) => formatTelefonLine(line))
							.join("\n");

					(teil.wohnungen || []).forEach((whg) => {
						const tenants = Array.isArray(whg.mieter) ? whg.mieter : [];
						const mieterCell = tenants.length
							? tenants
									.map((t) => {
										const label = frappe.utils.escape_html(t?.label || t?.contact || "");
										return t?.contact
											? `<a href="#" class="mieter-link" data-mieter="${t.contact}">${label}</a>`
											: label;
									})
									.join("<br>")
							: "";
						const wohnungLabel = frappe.utils.escape_html(whg.label || whg.name || "");
						const mietvertragName = whg.mietvertrag || "";
						const mietvertragAction = mietvertragName
							? `<a href="#" class="mietvertrag-link btn btn-xs btn-default" data-mietvertrag="${mietvertragName}">Mietvertrag</a>`
							: `<span class="text-muted">—</span>`;
						const telefonText = whg.telefon
							? frappe.utils.escape_html(formatTelefon(whg.telefon))
							: "";
						const telefonCell = `<div style="white-space: pre-wrap; line-height: 1.3;">${telefonText}</div>`;
						const whgRow = $(
							`<tr class="wohnung-row" data-immo-idx="${immoIdx}" data-teil-idx="${teilIdx}" style="display:none;">
<td></td>
<td></td>
<td>
<div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
<a href="#" class="wohnung-link" data-wohnung="${whg.name}" style="min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${wohnungLabel}</a>
<span style="flex:0 0 auto; display:inline-flex; justify-content:flex-end; min-width:92px;">${mietvertragAction}</span>
</div>
</td>
<td>${mieterCell}</td>
<td>${telefonCell}</td>
</tr>`
						);
						tbody.append(whgRow);

						// Click-Handler für Wohnung
						whgRow.find(".wohnung-link").on("click", function(e) {
							e.preventDefault();
							e.stopPropagation();
							frappe.set_route("Form", "Wohnung", whg.name);
						});

						// Click-Handler für Mietvertrag
						whgRow.find(".mietvertrag-link").on("click", function(e) {
							e.preventDefault();
							e.stopPropagation();
							const vertrag = $(this).data("mietvertrag");
							if (vertrag) {
								frappe.set_route("Form", "Mietvertrag", vertrag);
							}
						});

						// Click-Handler für Mieter (Contact)
						whgRow.find(".mieter-link").on("click", function (e) {
							e.preventDefault();
							e.stopPropagation();
							const mieter = $(this).data("mieter");
							if (mieter) {
								frappe.set_route("Form", "Contact", mieter);
							}
						});
					});

					teilRow.on("click", function (e) {
						e.stopPropagation();
						const rows = tbody.find(
							`tr.wohnung-row[data-immo-idx='${immoIdx}'][data-teil-idx='${teilIdx}']`
						);
						const visible = rows.first().is(":visible");
						rows.toggle(!visible);
						teilRow.find(".toggle-icon").text(visible ? "▶" : "▼");
					});
				});

				immoRow.on("click", function () {
					const teilRows = tbody.find(`tr.teil-row[data-immo-idx='${immoIdx}']`);
					const whgRows = tbody.find(`tr.wohnung-row[data-immo-idx='${immoIdx}']`);
					const visible = teilRows.first().is(":visible");

					if (visible) {
						teilRows.hide();
						whgRows.hide();
						teilRows.find(".toggle-icon").text("▶");
						immoRow.find(".toggle-icon").text("▶");
					} else {
						teilRows.show();
						whgRows.hide();
						teilRows.find(".toggle-icon").text("▶");
						immoRow.find(".toggle-icon").text("▼");
					}
				});
			});
			applyFilters();
		},
	});
};
