// postMessage-RPC-Bridge zwischen dem React-iframe und der Frappe-Host-Page.
//
// Der Editor läuft in einem iframe (Style-/Layout-Isolation) und hat daher kein
// eigenes `frappe.call`. Stattdessen schickt er Aktions-Anfragen an die Eltern-
// Page (hausverwaltung/page/serienbrief_editor/serienbrief_editor.js), die sie
// gegen eine feste Allowlist auf echte frappe.call-Aufrufe mappt und das Ergebnis
// zurückpostet.
//
// Standalone (npm run dev, ohne Frappe-Eltern) ist `isEmbedded()` false — die
// api.js fällt dann auf die Mock-Daten zurück.

const CLIENT = "hv-serienbrief";
const HOST = "hv-serienbrief-host";
const TIMEOUT_MS = 60000; // PDF-Vorschau via Chrome kann beim Kaltstart länger dauern

let _seq = 0;
const _pending = new Map();

export function isEmbedded() {
	try {
		return typeof window !== "undefined" && window.parent && window.parent !== window;
	} catch {
		return false;
	}
}

if (typeof window !== "undefined") {
	window.addEventListener("message", (event) => {
		const msg = event.data;
		if (!msg || msg.source !== HOST || msg.type !== "rpc-result") return;
		const entry = _pending.get(msg.id);
		if (!entry) return;
		_pending.delete(msg.id);
		clearTimeout(entry.timer);
		if (msg.ok) entry.resolve(msg.data);
		else entry.reject(new Error(msg.error || "RPC-Fehler"));
	});
}

// Eine Aktion an die Host-Page senden. `action` ist ein kurzer, von der Host-Page
// auf eine whitelisted Methode gemappter Bezeichner — kein freier Methodenname.
export function rpc(action, params = {}) {
	return new Promise((resolve, reject) => {
		if (!isEmbedded()) {
			reject(new Error("Editor läuft nicht eingebettet (kein Frappe-Host)."));
			return;
		}
		const id = `${CLIENT}-${++_seq}`;
		const timer = setTimeout(() => {
			if (_pending.has(id)) {
				_pending.delete(id);
				reject(new Error(`RPC-Timeout: ${action}`));
			}
		}, TIMEOUT_MS);
		_pending.set(id, { resolve, reject, timer });
		window.parent.postMessage(
			{ source: CLIENT, type: "rpc", id, action, params },
			window.location.origin
		);
	});
}
