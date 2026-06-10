// Bankimport v2 — Host-Page für die React-UI.
//
// Der Build (Vite) liegt unter
//   apps/hausverwaltung/hausverwaltung/public/bankimport_v2/
// und wird von Frappe unter /assets/hausverwaltung/bankimport_v2/ ausgeliefert.
//
// Bewusst per <iframe> eingebettet (nicht direkt ins Desk gemountet): das
// Prototyp-CSS nutzt globale Selektoren (body/button/input) und ein 100vh-Layout,
// die im Desk-DOM andere Seiten beeinflussen würden. Der iframe isoliert Styles,
// Fonts und Layout vollständig — exakt wie beim Serienbrief-Editor.
//
// Datenanbindung: Das iframe-UI hat kein eigenes frappe.call. Es schickt
// Aktions-Anfragen per postMessage an diese Host-Page (RPC_ACTIONS-Allowlist),
// die sie auf echte frappe.call-Aufrufe mappt — fast alle direkt auf die
// bestehende bankauszug_import.py-API. Das fügt KEINE Buchungslogik hinzu.

const DT = "hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.";
const PG = "hausverwaltung.hausverwaltung.page.bankimport_v2.bankimport_v2.";

// Erlaubte Aktionen → whitelisted Backend-Methoden. Das iframe kann ausschließlich
// diese kurzen Aktions-Namen auslösen, keine beliebigen Methoden.
const RPC_ACTIONS = {
	// Adapter (nur Lesen/Mappen)
	overview: PG + "get_overview",
	list_imports: PG + "list_imports",
	list_bank_accounts: PG + "list_bank_accounts",
	create_import: PG + "create_import",
	get_delete_impact: PG + "get_delete_impact",
	delete_import: PG + "delete_import",
	search_parties: PG + "search_parties",
	search_accounts: PG + "search_accounts",
	// Globale Aktionen
	parse_csv: DT + "parse_csv",
	refresh_saldo: DT + "refresh_saldo",
	create_bank_transactions: DT + "create_bank_transactions",
	create_bank_transaction_for_row: DT + "create_bank_transaction_for_row",
	retry_auto_match: DT + "retry_auto_match",
	relink_all_parties: DT + "relink_parties_for_all_rows",
	reset_row_booking: DT + "reset_row_booking",
	reset_row_processing: DT + "reset_row_processing",
	change_row_party: DT + "change_row_party",
	// Phase 1: Party zuordnen
	assign_party: DT + "apply_party_to_row_and_relink",
	create_party: DT + "create_party_and_bank_for_row",
	// Phase 3: Beleg zuordnen / buchen
	open_invoices: DT + "get_open_invoices_for_row",
	reconcile: DT + "manually_reconcile_row",
	standalone_payment: DT + "create_standalone_payment_for_row",
	journal_entry: DT + "create_journal_entry_for_row",
	expected_cost_center: DT + "get_expected_cost_center_for_row",
	abschlag_candidates: DT + "get_abschlagsplan_candidates_for_row",
	assign_abschlag: DT + "assign_abschlagsplan_row",
	kreditraten: DT + "get_open_kreditraten_for_row",
	assign_kreditrate: DT + "assign_kreditrate_to_bank_row",
	book_kreditrate_statement: DT + "book_kreditrate_from_statement_for_row",
};

// Navigations-Aktionen: kein frappe.call, sondern Desk-Navigation. Werden vom
// iframe wie eine RPC-Aktion aufgerufen, aber hier abgefangen.
const NAV_ACTIONS = {
	open_doc: (p) => p.doctype && p.docname && frappe.set_route("Form", p.doctype, p.docname),
	open_import_form: (p) => frappe.set_route("Form", "Bankauszug Import", p.docname),
	new_import: () => frappe.new_doc("Bankauszug Import"),
};

// Deep-Link: route_options.import (oder ?import=) wählt den konkreten Import.
function consumeImportRoute() {
	const ro = frappe.route_options || {};
	let name = ro.import || ro.bankauszug_import || "";
	if (name) delete frappe.route_options.import;
	if (!name) name = (frappe.utils.get_query_params() || {}).import || "";
	return name || "";
}

function buildSrc(importName) {
	let s = `/assets/hausverwaltung/bankimport_v2/index.html?v=${Date.now()}`;
	if (importName) s += `&import=${encodeURIComponent(importName)}`;
	return s;
}

let _reload = null;
let _onMessage = null;
let _resize = null;
let _listenerActive = false;
let _resizeActive = false;

function attachListener() {
	if (_onMessage && !_listenerActive) {
		window.addEventListener("message", _onMessage);
		_listenerActive = true;
	}
}

function detachListener() {
	if (_onMessage && _listenerActive) {
		window.removeEventListener("message", _onMessage);
		_listenerActive = false;
	}
}

function attachResize() {
	if (_resize && !_resizeActive) {
		$(window).on("resize.hv_bankimport", frappe.utils.debounce(_resize, 100));
		_resizeActive = true;
	}
}

function detachResize() {
	if (_resizeActive) {
		$(window).off("resize.hv_bankimport");
		_resizeActive = false;
	}
}

// Erneute Navigation (z.B. aus dem Bankauszug-Import-Formular) mit neuem Import:
// on_page_load läuft bei gecachter Page nicht erneut, on_page_show schon.
frappe.pages["bankimport_v2"].on_page_show = function () {
	attachListener();
	attachResize();
	if (_resize) _resize();
	const name = consumeImportRoute();
	if (name && _reload) _reload(name);
};

frappe.pages["bankimport_v2"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bankimport"),
		single_column: true,
	});

	const $body = $(page.body);
	$body.empty().css({ padding: 0, margin: 0 });

	const src = buildSrc(consumeImportRoute());
	const $frame = $(
		`<iframe class="hv-bankimport-frame" src="${src}" title="Bankimport"></iframe>`
	).css({ width: "100%", border: "none", display: "block", background: "#f7f6f3" });

	$body.append($frame);
	_reload = (name) => $frame.attr("src", buildSrc(name));

	function resize() {
		const top = $frame[0].getBoundingClientRect().top;
		const h = Math.max(480, window.innerHeight - top - 8);
		$frame.css("height", `${h}px`);
	}
	_resize = resize;
	resize();
	attachResize();

	// --- postMessage-RPC-Host -------------------------------------------------
	const onMessage = (event) => {
		if (event.source !== $frame[0].contentWindow) return;
		if (event.origin !== window.location.origin) return;

		const msg = event.data;
		if (!msg || msg.source !== "hv-bankimport" || msg.type !== "rpc") return;

		const reply = (payload) =>
			event.source.postMessage(
				{ source: "hv-bankimport-host", type: "rpc-result", id: msg.id, ...payload },
				event.origin
			);

		const nav = NAV_ACTIONS[msg.action];
		if (nav) {
			try {
				nav(msg.params || {});
				reply({ ok: true, data: {} });
			} catch (e) {
				reply({ ok: false, error: extractError(e) });
			}
			return;
		}

		const method = RPC_ACTIONS[msg.action];
		if (!method) {
			reply({ ok: false, error: `Unbekannte Aktion: ${msg.action}` });
			return;
		}

		frappe
			.call({ method, args: msg.params || {} })
			.then((r) => reply({ ok: true, data: r.message }))
			.catch((e) => reply({ ok: false, error: extractError(e) }));
	};

	// Aus einem fehlgeschlagenen frappe.call eine lesbare Meldung ziehen.
	function extractError(e) {
		if (!e) return __("Unbekannter Fehler");
		if (typeof e === "string") return e;
		if (e.message) return e.message;
		const sm = e._server_messages || (e.responseJSON && e.responseJSON._server_messages);
		if (sm) {
			try {
				return JSON.parse(sm)
					.map((m) => {
						try {
							return JSON.parse(m).message;
						} catch (_) {
							return m;
						}
					})
					.join("; ");
			} catch (_) {
				return String(sm);
			}
		}
		if (e.responseJSON && e.responseJSON.exception) return e.responseJSON.exception;
		try {
			return JSON.stringify(e);
		} catch (_) {
			return String(e);
		}
	}

	_onMessage = onMessage;
	attachListener();

	// Frappe cached Pages nach der Navigation weg vom iframe. Deshalb wird der
	// postMessage-Listener beim nächsten on_page_show wieder aktiviert.
	page.wrapper.on("hide", () => {
		detachResize();
		detachListener();
	});
};
