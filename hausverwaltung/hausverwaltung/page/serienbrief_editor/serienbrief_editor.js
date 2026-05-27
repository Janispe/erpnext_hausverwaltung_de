// Serienbrief Editor (Beta) — parallele, eigenständige React-UI.
//
// Der React-Build (Vite) liegt unter
//   apps/hausverwaltung/hausverwaltung/public/serienbrief_editor/
// und wird von Frappe unter /assets/hausverwaltung/serienbrief_editor/ ausgeliefert.
//
// Bewusst per <iframe> eingebettet (nicht direkt ins Desk gemountet): das
// Prototyp-CSS nutzt globale Selektoren (body/button/input) und ein 100vh-Layout,
// die im Desk-DOM andere Seiten beeinflussen würden. Der iframe isoliert Styles,
// Fonts und Layout vollständig.
//
// Datenanbindung: Das iframe-UI hat kein eigenes frappe.call. Es schickt Aktions-
// Anfragen per postMessage an diese Host-Page (siehe RPC_ACTIONS-Allowlist unten),
// die sie auf echte frappe.call-Aufrufe mappt und das Ergebnis zurückpostet.

// Erlaubte Aktionen → whitelisted Backend-Methoden. Das iframe kann ausschließlich
// diese kurzen Aktions-Namen auslösen, keine beliebigen Methoden.
const HV_SB = "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.";
const RPC_ACTIONS = {
	tree: HV_SB + "get_editor_tree",
	template: HV_SB + "get_editor_template",
	save: HV_SB + "save_editor_template",
	bausteine: HV_SB + "get_editor_bausteine",
	placeholder_tree: HV_SB + "get_editor_placeholder_tree",
	recipients: HV_SB + "get_editor_recipients",
	preview: HV_SB + "render_template_preview_pdf",
	editor_preview: HV_SB + "render_editor_preview_pdf",
	baustein_previews: HV_SB + "render_editor_baustein_previews",
	editor_print_css: HV_SB + "get_editor_print_format_css",
	upload_image: HV_SB + "upload_editor_image",
	copy: HV_SB + "copy_serienbrief_vorlage",
	delete: HV_SB + "delete_serienbrief_vorlage",
};

// Navigations-Aktionen: kein frappe.call, sondern öffnen ein Desk-Formular. Werden
// vom iframe wie eine normale RPC-Aktion aufgerufen, aber hier abgefangen.
const NAV_ACTIONS = {
	// Neues "Serienbrief Durchlauf"-Formular mit vorausgewählter Vorlage. Die
	// Kategorie/iteration_doctype füllt das Durchlauf-Formular selbst aus der Vorlage
	// (hv_apply_incoming_route_options + vorlage-onchange).
	new_durchlauf: (params) => {
		frappe.route_options = { hv_vorlage: params.vorlage || undefined };
		frappe.set_route("serienbrief_durchlauf_viewer");
	},
	// Escape-Hatch zur klassischen Form: nötig für den geführten Mapping-Wizard
	// und Spezialfälle wie Mehrfach-Baustein-Mappings, die das alte Child-Table-
	// Datenmodell (textbausteine[].pfad_zuordnung) abbildet, das Inline-Modell
	// des neuen Editors aber nicht.
	open_classic_form: (params) => {
		if (params.vorlage) frappe.set_route("Form", "Serienbrief Vorlage", params.vorlage);
	},
	// "Zurück zur Liste"-Button im Editor-Header — springt zum neuen
	// Vorlagen-Browser (Default-Einstieg seit Soft-Switch).
	open_browser: () => {
		frappe.set_route("serienbrief_browser");
	},
};

// Deep-Link aus dem Vorlagen-Browser: route_options.hv_serienbrief_template wird
// an das iframe als ?template=<name> weitergereicht; der React-Editor wählt diese
// Vorlage beim Start aus. Wir konsumieren den Param (einmalig), damit ein späterer
// normaler Aufruf der Page nicht wieder dieselbe Vorlage erzwingt.
let _editorReload = null;

function consumeTemplateRoute() {
	const ro = frappe.route_options || {};
	const t = ro.hv_serienbrief_template;
	if (t) delete frappe.route_options.hv_serienbrief_template;
	return t || "";
}

function buildEditorSrc(template) {
	let s = `/assets/hausverwaltung/serienbrief_editor/index.html?v=${Date.now()}`;
	if (template) s += `&template=${encodeURIComponent(template)}`;
	return s;
}

// Modul-Scope für den message-Listener, damit on_page_show ihn nach einem
// "hide" (Page-Wechsel) wieder reaktivieren kann. Sonst sind nach einmaligem
// Verlassen alle postMessage-Aktionen (Speichern, Vorschau …) im Editor tot.
let _editorOnMessage = null;
let _editorListenerActive = false;

function _attachEditorListener() {
	if (_editorOnMessage && !_editorListenerActive) {
		window.addEventListener("message", _editorOnMessage);
		_editorListenerActive = true;
	}
}

function _detachEditorListener() {
	if (_editorOnMessage && _editorListenerActive) {
		window.removeEventListener("message", _editorOnMessage);
		_editorListenerActive = false;
	}
}

// Erneute Navigation Browser → Editor: on_page_load läuft bei gecachter Page nicht
// noch einmal, on_page_show schon. Hier das iframe mit der neuen Vorlage neu laden
// und den Listener reaktivieren.
frappe.pages["serienbrief_editor"].on_page_show = function () {
	_attachEditorListener();
	const t = consumeTemplateRoute();
	if (t && _editorReload) _editorReload(t);
};

frappe.pages["serienbrief_editor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Serienbrief Editor (Beta)"),
		single_column: true,
	});

	const $body = $(page.body);
	$body.empty().css({ padding: 0, margin: 0 });

	// Cache-Bust pro Aufruf, damit nach einem Rebuild immer der aktuelle Build
	// geladen wird (interne Beta — der Re-Download von ~60 KB gzip ist unkritisch).
	// Optionaler Deep-Link-Param ?template=<name> (aus dem Vorlagen-Browser).
	const src = buildEditorSrc(consumeTemplateRoute());

	const $frame = $(
		`<iframe class="hv-serienbrief-editor-frame" src="${src}" title="Serienbrief Editor"></iframe>`
	).css({
		width: "100%",
		border: "none",
		display: "block",
		background: "#f6f5f1",
	});

	$body.append($frame);

	// Reloader für erneute Browser → Editor-Navigation (siehe on_page_show oben).
	_editorReload = (template) => $frame.attr("src", buildEditorSrc(template));

	// iframe füllt den Platz bis zum Fensterende.
	function resize() {
		const top = $frame[0].getBoundingClientRect().top;
		const h = Math.max(480, window.innerHeight - top - 8);
		$frame.css("height", `${h}px`);
	}

	resize();
	$(window).on("resize.hv_serienbrief_editor", frappe.utils.debounce(resize, 100));

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

		// Navigations-Aktion? -> Desk-Formular öffnen (kein frappe.call).
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
	// im iframe nur "[object Object]". Frappe legt Server-Fehler je nach Pfad an
	// verschiedenen Stellen ab.
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

	_editorOnMessage = onMessage;
	_attachEditorListener();

	// Aufräumen, wenn die Seite verlassen wird. Reaktiviert wird der Listener
	// beim nächsten on_page_show via _attachEditorListener().
	page.wrapper.on("hide", () => {
		$(window).off("resize.hv_serienbrief_editor");
		_detachEditorListener();
	});
};
