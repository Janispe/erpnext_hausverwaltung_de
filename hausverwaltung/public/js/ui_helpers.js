// Stellt UI-Helfer für Hausverwaltungs-Custom-JS bereit.
//
// `window.hausverwaltung.ui.widen_modal(dialog)`
//   Stretcht ein Frappe-Dialog (insb. MultiSelectDialog, dessen Default 800px
//   für Mietvertrag-Anzeigenamen oft zu schmal ist) auf eine Viewport-relative
//   Breite. Der Wert kommt aus Hausverwaltung Einstellungen
//   → "Picker-Modal-Breite (% Viewport)" und wird via boot exposed
//   (`frappe.boot.hv_ui.picker_modal_width_vw`).
//
//   Ist der Wert 0 / leer / nicht gesetzt → keine Änderung (Frappe-Default).
//   Beim Render-Race rufen wir den Setzer mehrfach (asyncrone Bootstrap-
//   Modal-Animation) und an `shown.bs.modal` an.

(function () {
	function _get_target_width_vw() {
		try {
			const v = frappe.boot && frappe.boot.hv_ui && frappe.boot.hv_ui.picker_modal_width_vw;
			return Number(v) || 0;
		} catch (e) {
			return 0;
		}
	}

	function widen_modal(dialog) {
		if (!dialog) return;
		const vw = _get_target_width_vw();
		if (!vw || vw <= 0) return; // Default behalten
		const css_value = `${vw}vw`;

		const apply = () => {
			// Strategie: erst $wrapper, dann dialog.dialog.$wrapper, sonst
			// global im document nach dem zuletzt geöffneten Modal suchen.
			let $dlg = null;
			let $wrapper = dialog.$wrapper;
			if (!$wrapper && dialog.dialog && dialog.dialog.$wrapper) {
				$wrapper = dialog.dialog.$wrapper;
			}
			if ($wrapper && $wrapper.length) {
				const found = $wrapper.find(".modal-dialog");
				if (found.length) $dlg = found;
			}
			if (!$dlg) {
				// Fallback: Bootstrap appendet Modal in body. Letztes sichtbares.
				const all = $(".modal-dialog:visible");
				if (all.length) $dlg = all.last();
			}
			if (!$dlg || !$dlg.length) return false;
			$dlg.css({ "max-width": css_value, width: css_value });
			$dlg.find(".modal-body, .multiselect-list").css({ "max-width": "100%" });
			return true;
		};

		apply("sync");
		[0, 50, 150, 300, 600].forEach((d) => setTimeout(() => apply(`t${d}`), d));
		const $w = dialog.$wrapper || (dialog.dialog && dialog.dialog.$wrapper);
		if ($w) {
			$w.on("shown.bs.modal", () => apply("shown"));
		}
	}

	window.hausverwaltung = window.hausverwaltung || {};
	window.hausverwaltung.ui = window.hausverwaltung.ui || {};
	window.hausverwaltung.ui.widen_modal = widen_modal;
})();
