// Kleiner localStorage-Helper für UI-Präferenzen (Sidebar-Breite, Vorlagen auf/zu,
// offene Kategorien, aktiver Tab). Pro Browser/Origin — übersteht Neuladen & Sessions.
const PREFIX = "hv-serienbrief-editor:";

export function loadPref(key, fallback) {
	try {
		const v = localStorage.getItem(PREFIX + key);
		return v == null ? fallback : JSON.parse(v);
	} catch {
		return fallback;
	}
}

export function savePref(key, value) {
	try {
		localStorage.setItem(PREFIX + key, JSON.stringify(value));
	} catch {
		/* localStorage nicht verfügbar -> ignorieren */
	}
}
