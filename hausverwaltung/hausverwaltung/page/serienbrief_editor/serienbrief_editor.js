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
const RPC_ACTIONS = {
	tree: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.get_editor_tree",
	template:
		"hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.get_editor_template",
	save: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.save_editor_template",
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
	const src = `/assets/hausverwaltung/serienbrief_editor/index.html?v=${Date.now()}`;

	const $frame = $(
		`<iframe class="hv-serienbrief-editor-frame" src="${src}" title="Serienbrief Editor"></iframe>`
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

		const method = RPC_ACTIONS[msg.action];
		if (!method) {
			reply({ ok: false, error: `Unbekannte Aktion: ${msg.action}` });
			return;
		}

		frappe
			.call({ method, args: msg.params || {} })
			.then((r) => reply({ ok: true, data: r.message }))
			.catch((e) => reply({ ok: false, error: (e && e.message) || String(e) }));
	};

	window.addEventListener("message", onMessage);

	// Aufräumen, wenn die Seite verlassen wird.
	page.wrapper.on("hide", () => {
		$(window).off("resize.hv_serienbrief_editor");
		window.removeEventListener("message", onMessage);
	});
};
