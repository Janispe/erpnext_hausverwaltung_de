// Stellt wiederverwendbare Datums-Schnellauswahlen bereit (Aktuelles Jahr,
// Vorjahr, Aktuelles Quartal, Vorquartal, Aktueller Monat, Vormonat, Gesamt).
//
// Benutzung in einem Form-Skript:
//
//   frappe.ui.form.on("My Doctype", {
//       refresh(frm) {
//           hausverwaltung.date_presets.attach_to_form(frm, {
//               from_field: "from_date",
//               to_field: "to_date",
//           });
//       },
//   });
//
// Optional in einem Dialog/Custom-Page mit beliebigem Container:
//   hausverwaltung.date_presets.render_buttons($container, {
//       on_select(range) { /* range = {from, to} als YYYY-MM-DD Strings */ },
//   });

(function () {
	const ymd = (m) => m.format("YYYY-MM-DD");

	function build_presets(options) {
		const include_gesamt = options && options.include_gesamt !== false;
		const today = moment();
		const presets = [
			{
				key: "current_year",
				label: __("Aktuelles Jahr"),
				range: () => ({
					from: ymd(moment().startOf("year")),
					to: ymd(moment().endOf("year")),
				}),
			},
			{
				key: "previous_year",
				label: __("Vorjahr"),
				range: () => ({
					from: ymd(moment().subtract(1, "year").startOf("year")),
					to: ymd(moment().subtract(1, "year").endOf("year")),
				}),
			},
			{
				key: "current_quarter",
				label: __("Aktuelles Quartal"),
				range: () => ({
					from: ymd(moment().startOf("quarter")),
					to: ymd(moment().endOf("quarter")),
				}),
			},
			{
				key: "previous_quarter",
				label: __("Vorquartal"),
				range: () => ({
					from: ymd(moment().subtract(1, "quarter").startOf("quarter")),
					to: ymd(moment().subtract(1, "quarter").endOf("quarter")),
				}),
			},
			{
				key: "current_month",
				label: __("Aktueller Monat"),
				range: () => ({
					from: ymd(moment().startOf("month")),
					to: ymd(moment().endOf("month")),
				}),
			},
			{
				key: "previous_month",
				label: __("Vormonat"),
				range: () => ({
					from: ymd(moment().subtract(1, "month").startOf("month")),
					to: ymd(moment().subtract(1, "month").endOf("month")),
				}),
			},
			{
				key: "last_12_months",
				label: __("Letzte 12 Monate"),
				range: () => ({
					from: ymd(moment().subtract(12, "months").add(1, "day")),
					to: ymd(today),
				}),
			},
		];
		if (include_gesamt) {
			presets.push({
				key: "all_time",
				label: __("Gesamt"),
				range: () => ({ from: null, to: null }),
			});
		}
		return presets;
	}

	function render_buttons($container, opts) {
		const options = opts || {};
		const presets = build_presets(options);

		$container.empty();
		$container.addClass("hv-date-presets");

		presets.forEach((preset) => {
			const $btn = $(
				`<button type="button" class="btn btn-xs btn-default hv-date-preset-btn">${frappe.utils.escape_html(preset.label)}</button>`
			);
			$btn.on("click", () => {
				const range = preset.range();
				if (typeof options.on_select === "function") {
					options.on_select(range, preset);
				}
			});
			$container.append($btn);
		});

		return $container;
	}

	function _do_attach(frm, opts) {
		const from_field = opts.from_field;
		const to_field = opts.to_field;
		const wrapper_id = `hv-date-presets-${from_field}-${to_field}`;

		const anchor_field = frm.fields_dict[opts.anchor_field || from_field];
		if (!anchor_field || !anchor_field.$wrapper) return false;

		// Mehrfachaufruf (z.B. bei refresh) verhindern
		anchor_field.$wrapper.find(`#${wrapper_id}`).remove();

		const $row = $(
			`<div id="${wrapper_id}" class="hv-date-presets-row" style="margin:6px 0 4px; padding:4px 0; display:flex; flex-wrap:wrap; gap:4px; align-items:center;"><span style="font-size:11px; color:#8d99a6; margin-right:4px;">${__("Schnellauswahl:")}</span></div>`
		);
		anchor_field.$wrapper.append($row);

		render_buttons($row, {
			include_gesamt: opts.include_gesamt,
			on_select(range) {
				frm.set_value(from_field, range.from);
				frm.set_value(to_field, range.to);
			},
		});
		return true;
	}

	function attach_to_form(frm, opts) {
		if (!frm || !opts || !opts.from_field || !opts.to_field) return;
		// Direkt + nach Render-Tick erneut, weil Frappe das Field-Wrapper
		// gelegentlich nach `refresh` neu rendert.
		_do_attach(frm, opts);
		setTimeout(() => _do_attach(frm, opts), 0);
		setTimeout(() => _do_attach(frm, opts), 200);
	}

	function attach_to_query_report(report, opts) {
		if (!report || !report.page || !opts || !opts.from_field || !opts.to_field) return;
		const presets = build_presets(opts);
		const group_label = opts.group_label || __("Zeitraum");

		presets.forEach((preset) => {
			try {
				report.page.remove_inner_button(preset.label, group_label);
			} catch {
				// ignore
			}
			report.page.add_inner_button(
				preset.label,
				() => {
					const range = preset.range();
					const values = {};
					values[opts.from_field] = range.from;
					values[opts.to_field] = range.to;
					frappe.query_report.set_filter_value(values);
				},
				group_label
			);
		});
	}

	window.hausverwaltung = window.hausverwaltung || {};
	window.hausverwaltung.date_presets = {
		attach_to_form,
		attach_to_query_report,
		render_buttons,
		build_presets,
	};
})();
