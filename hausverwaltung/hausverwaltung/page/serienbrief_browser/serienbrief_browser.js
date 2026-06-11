// Serienbrief Vorlagen-Browser — parallele, eigenständige React-UI.
//
// Der React-Build (Vite) liegt unter
//   apps/hausverwaltung/hausverwaltung/public/serienbrief_browser/
// und wird von Frappe unter /assets/hausverwaltung/serienbrief_browser/ ausgeliefert.
//
// Bewusst per <iframe> eingebettet (nicht direkt ins Desk gemountet): das Prototyp-
// CSS nutzt globale Selektoren (body/button/input) und ein 100vh-Layout, die im
// Desk-DOM andere Seiten beeinflussen würden. Der iframe isoliert Styles vollständig.
//
// Datenanbindung wie beim Serienbrief Editor: Das iframe-UI hat kein eigenes
// frappe.call. Es schickt Aktions-Anfragen per postMessage an diese Host-Page (siehe
// RPC_ACTIONS-Allowlist), die sie auf echte frappe.call-Aufrufe mappt und das
// Ergebnis zurückpostet.

// Erlaubte Aktionen → whitelisted Backend-Methoden. Das iframe kann ausschließlich
// diese kurzen Aktions-Namen auslösen, keine beliebigen Methoden.
const HV_SB = "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.";
const RPC_ACTIONS = {
	browser_data: HV_SB + "get_browser_data",
	set_favorite: HV_SB + "set_template_favorite",
	move: HV_SB + "move_templates_to_kategorie",
	create_folder: HV_SB + "create_kategorie",
	create_template: HV_SB + "create_serienbrief_vorlage",
	copy: HV_SB + "copy_serienbrief_vorlage",
	delete: HV_SB + "delete_serienbrief_vorlage",
	recipients: HV_SB + "get_editor_recipients",
	preview: HV_SB + "render_template_preview_pdf",
};

// Navigations-Aktionen: kein frappe.call, sondern öffnen ein Desk-Formular bzw. eine
// andere Page. Werden vom iframe wie eine normale RPC-Aktion aufgerufen, aber hier
// abgefangen.
const NAV_ACTIONS = {
	// Neuer Durchlauf in der Vollbild-Page (Vorlage vorausgewählt).
	new_durchlauf: (params) => {
		frappe.route_options = { hv_vorlage: params.vorlage || undefined };
		frappe.set_route("serienbrief_durchlauf_viewer");
	},
	// Vorlage im Serienbrief Editor öffnen (vorausgewählt via route_options →
	// die Editor-Host-Page reicht den Param ans iframe weiter).
	open_editor: (params) => {
		frappe.route_options = { hv_serienbrief_template: params.template || undefined };
		frappe.set_route("serienbrief_editor");
	},
};

// Modul-Scope, damit on_page_show den im on_page_load installierten Listener
// nach einem "hide"/Page-Wechsel wieder reaktivieren kann.
let _browserOnMessage = null;
let _browserListenerActive = false;

function _attachBrowserListener() {
	if (_browserOnMessage && !_browserListenerActive) {
		window.addEventListener("message", _browserOnMessage);
		_browserListenerActive = true;
	}
}

function _detachBrowserListener() {
	if (_browserOnMessage && _browserListenerActive) {
		window.removeEventListener("message", _browserOnMessage);
		_browserListenerActive = false;
	}
}

// on_page_load läuft bei gecachter Page nicht noch einmal, on_page_show schon.
// Ohne Re-Attach hier verliert der Browser nach „Durchlauf öffnen → Zurück" alle
// postMessage-Aktionen (z.B. erneutes Klicken auf „Durchlauf" macht nichts).
frappe.pages["serienbrief_browser"].on_page_show = function () {
	_attachBrowserListener();
};

frappe.pages["serienbrief_browser"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Serienbrief Vorlagen-Browser"),
		single_column: true,
	});

	const $body = $(page.body);
	$body.empty().css({ padding: 0, margin: 0 });

	// Cache-Bust pro Aufruf, damit nach einem Rebuild immer der aktuelle Build geladen wird.
	// Das Deploy-Skript legt den Browser-Build als index.html ab (dist/browser.html →
	// serienbrief_browser/index.html), daher index.html laden — nicht browser.html.
	const src = `/assets/hausverwaltung/serienbrief_browser/index.html?v=${Date.now()}`;

	const $frame = $(
		`<iframe class="hv-serienbrief-browser-frame" src="${src}" title="Serienbrief Vorlagen-Browser"></iframe>`
	).css({
		width: "100%",
		border: "none",
		display: "block",
		background: "#f6f5f1",
	});

	$body.append($frame);

	// iframe füllt den Platz bis zum Fensterende.
	function resize() {
		const top = $frame[0].getBoundingClientRect().top;
		const h = Math.max(480, window.innerHeight - top - 8);
		$frame.css("height", `${h}px`);
	}

	resize();
	$(window).on("resize.hv_serienbrief_browser", frappe.utils.debounce(resize, 100));

	// --- postMessage-RPC-Host -------------------------------------------------
	const onMessage = (event) => {
		// Nur Nachrichten aus genau diesem iframe und gleicher Origin akzeptieren.
		if (event.source !== $frame[0].contentWindow) return;
		if (event.origin !== window.location.origin) return;

		const msg = event.data;
		if (!msg || msg.source !== "hv-serienbrief" || msg.type !== "rpc") return;

		const reply = (payload) =>
			event.source.postMessage(
				{ source: "hv-serienbrief-host", type: "rpc-result", id: msg.id, ...payload },
				event.origin
			);

		// Navigations-Aktion? -> Desk-Formular/Page öffnen (kein frappe.call).
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

	// Aus einem fehlgeschlagenen frappe.call eine lesbare Meldung ziehen — sonst landet
	// im iframe nur "[object Object]".
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

	_browserOnMessage = onMessage;
	_attachBrowserListener();

	// Aufräumen, wenn die Seite verlassen wird. Der Listener wird beim erneuten
	// on_page_show via _attachBrowserListener() reaktiviert.
	page.wrapper.on("hide", () => {
		$(window).off("resize.hv_serienbrief_browser");
		_detachBrowserListener();
	});
};
