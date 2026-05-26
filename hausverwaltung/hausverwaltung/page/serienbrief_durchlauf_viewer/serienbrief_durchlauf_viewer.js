// Serienbrief Durchlauf — eigenständige Vollbild-React-UI (wie der Serienbrief Editor).
//
// Der React-Build liegt unter
//   apps/hausverwaltung/hausverwaltung/public/serienbrief_durchlauf/
// und wird unter /assets/hausverwaltung/serienbrief_durchlauf/ ausgeliefert.
//
// Route: /app/serienbrief_durchlauf_viewer            → „Neuer Durchlauf"-Modus
//        /app/serienbrief_durchlauf_viewer/<docname>  → Viewer für diesen Durchlauf
//
// Datenanbindung wie Editor/Browser: postMessage-Bridge → Host mappt kurze Aktions-
// Namen auf whitelisted Methoden. Das Durchlauf-Doctype-Formular leitet hierher um,
// sodass nur diese UI zu sehen ist (kein Standardformular drumherum).

const HV_DL = "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.";
const RPC_ACTIONS = {
	durchlauf_data: HV_DL + "get_durchlauf_data",
	run_progress: HV_DL + "get_run_progress",
	start_run: HV_DL + "start_durchlauf_run",
	set_variables: HV_DL + "set_run_variables",
	add_recipients: HV_DL + "add_recipients",
	remove_recipients: HV_DL + "remove_recipients",
	available_recipients: HV_DL + "get_available_recipients",
	merged_pdf: HV_DL + "get_merged_pdf",
	create: HV_DL + "create_durchlauf",
	update: HV_DL + "update_durchlauf",
	list_vorlagen: HV_DL + "list_vorlagen",
	mark_failed: HV_DL + "mark_durchlauf_failed",
};

// Navigations-Aktionen (kein frappe.call).
const NAV_ACTIONS = {
	// Nach „Neuer Durchlauf" auf die docname-Route wechseln (reload-/teilbar).
	goto_durchlauf: (params) => frappe.set_route("serienbrief_durchlauf_viewer", params.docname),
	// In den „Neuer Durchlauf"-Modus (Route ohne docname).
	new_durchlauf: () => frappe.set_route("serienbrief_durchlauf_viewer"),
	open_list: () => frappe.set_route("List", "Serienbrief Durchlauf"),
	// Klassisches Formular öffnen (Debug/Fallback) — Flag verhindert Re-Redirect.
	open_form: (params) => {
		frappe.route_options = { hv_show_form: 1 };
		frappe.set_route("Form", "Serienbrief Durchlauf", params.docname);
	},
};

let _frame = null;
let _currentDocname = null;

function dl_route_docname() {
	const route = frappe.get_route() || [];
	return route[1] || "";
}

// Vorausgewählte Vorlage (aus dem Browser „Durchlauf starten") einmalig konsumieren.
function dl_consume_vorlage() {
	const v = frappe.route_options && frappe.route_options.hv_vorlage;
	if (v) delete frappe.route_options.hv_vorlage;
	return v || "";
}

function dl_build_src(docname, vorlage) {
	let s = `/assets/hausverwaltung/serienbrief_durchlauf/index.html?v=${Date.now()}`;
	if (docname) s += `&docname=${encodeURIComponent(docname)}`;
	if (!docname && vorlage) s += `&vorlage=${encodeURIComponent(vorlage)}`;
	return s;
}

// Bei Navigation auf eine andere/neue docname-Route (oder frischer Vorlage-Vorauswahl)
// das iframe neu laden.
frappe.pages["serienbrief_durchlauf_viewer"].on_page_show = function () {
	const docname = dl_route_docname();
	const vorlage = dl_consume_vorlage();
	if (_frame && (docname !== _currentDocname || (!docname && vorlage))) {
		_currentDocname = docname;
		_frame.attr("src", dl_build_src(docname, vorlage));
	}
};

frappe.pages["serienbrief_durchlauf_viewer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Serienbrief Durchlauf"),
		single_column: true,
	});

	const $body = $(page.body);
	$body.empty().css({ padding: 0, margin: 0 });

	_currentDocname = dl_route_docname();
	const $frame = $(
		`<iframe class="hv-serienbrief-durchlauf-frame" src="${dl_build_src(_currentDocname, dl_consume_vorlage())}" title="Serienbrief Durchlauf"></iframe>`
	).css({ width: "100%", border: "none", display: "block", background: "#f6f5f1" });
	$body.append($frame);
	_frame = $frame;

	function resize() {
		const top = $frame[0].getBoundingClientRect().top;
		$frame.css("height", `${Math.max(480, window.innerHeight - top - 8)}px`);
	}
	resize();
	$(window).on("resize.hv_serienbrief_durchlauf", frappe.utils.debounce(resize, 100));

	const onMessage = (event) => {
		if (event.source !== $frame[0].contentWindow) return;
		if (event.origin !== window.location.origin) return;
		const msg = event.data;
		if (!msg || msg.source !== "hv-serienbrief" || msg.type !== "rpc") return;

		const reply = (payload) =>
			event.source.postMessage(
				{ source: "hv-serienbrief-host", type: "rpc-result", id: msg.id, ...payload },
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

	window.addEventListener("message", onMessage);

	page.wrapper.on("hide", () => {
		$(window).off("resize.hv_serienbrief_durchlauf");
		window.removeEventListener("message", onMessage);
	});
};
