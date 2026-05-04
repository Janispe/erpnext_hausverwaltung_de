"""Bundesbank-BLZ-Datei-Loader und IBAN-Lookup.

Pflegt das DocType ``BLZ Mapping`` mit den aktuellen deutschen Bankleitzahlen
aus der offiziellen Bankleitzahlendatei der Deutschen Bundesbank.

- ``load_blz_data()`` lädt die Datei (auto-erkannte URL oder konfigurierte URL),
  parst sie und upserted die Einträge.
- ``lookup_iban(iban)`` liest aus einer DE-IBAN die BLZ und liefert das gemappte
  Bank-Dict oder None.

Format-Spec der Bundesbank-Datei (fixed-width, ISO-8859-1):
- Pos 1-8:    Bankleitzahl
- Pos 9:      Merkmal ('1' = nimmt Zahlungsverkehr teil)
- Pos 10-67:  Bezeichnung (Bankname)
- Pos 68-72:  PLZ
- Pos 73-107: Ort
- Pos 140-150: BIC
"""

from __future__ import annotations

import re
from typing import Any

import frappe
import requests

BUNDESBANK_BASE = "https://www.bundesbank.de"
DEFAULT_BUNDESBANK_PAGE = (
	f"{BUNDESBANK_BASE}/de/aufgaben/unbarer-zahlungsverkehr/"
	"serviceangebot/bankleitzahlen/download-bankleitzahlen-602592"
)
USER_AGENT = "hausverwaltung-frappe/1.0"
DOWNLOAD_TIMEOUT = 60
# Bundesbank-Seite verlinkt das Aktuell-File als blz-aktuell-txt-data.txt
# (relative URL — wir lassen sowohl absolute als auch relative Pfade zu).
BLZ_FILE_LINK_PATTERN = re.compile(
	r'href="(?P<url>(?:https?://[^"]*?|/[^"]*?)blz-aktuell-txt-data\.txt)"',
	re.IGNORECASE,
)


class BlzLoaderError(RuntimeError):
	pass


def _settings_url() -> str | None:
	settings = frappe.get_single("Hausverwaltung Einstellungen")
	url = (getattr(settings, "blz_datei_url", None) or "").strip()
	return url or None


def find_blz_url(page_url: str = DEFAULT_BUNDESBANK_PAGE) -> str:
	"""Scrapt die Bundesbank-Download-Seite nach der aktuellen .txt-URL."""
	try:
		resp = requests.get(
			page_url,
			headers={"User-Agent": USER_AGENT},
			timeout=DOWNLOAD_TIMEOUT,
		)
	except requests.RequestException as exc:
		raise BlzLoaderError(f"Bundesbank-Seite nicht erreichbar: {exc}") from exc
	if resp.status_code != 200:
		raise BlzLoaderError(
			f"Bundesbank-Seite Status {resp.status_code}: {resp.text[:200]}"
		)
	for match in BLZ_FILE_LINK_PATTERN.finditer(resp.text):
		url = match.group("url")
		if url.startswith("/"):
			url = BUNDESBANK_BASE + url
		return url
	raise BlzLoaderError(
		f"Kein .txt-Download-Link auf {page_url} gefunden — Seitenstruktur eventuell geändert."
	)


def download_blz_file(url: str) -> bytes:
	try:
		resp = requests.get(
			url,
			headers={"User-Agent": USER_AGENT},
			timeout=DOWNLOAD_TIMEOUT,
		)
	except requests.RequestException as exc:
		raise BlzLoaderError(f"BLZ-Datei-Download fehlgeschlagen: {exc}") from exc
	if resp.status_code != 200:
		raise BlzLoaderError(f"BLZ-Datei Status {resp.status_code}")
	return resp.content


def parse_blz_file(content: bytes):
	"""Parst die fixed-width-Datei. Gibt ein Iterator über Dicts zurück.

	Encoding: Bundesbank-Datei ist ISO-8859-1.
	"""
	text = content.decode("iso-8859-1", errors="replace")
	for line in text.splitlines():
		# Mindestlänge ~150 Zeichen für eine vollständige Zeile.
		if len(line) < 150:
			continue
		merkmal = line[8:9]
		# Wir nehmen nur "1" (nimmt am Zahlungsverkehr teil) — die anderen Marker
		# sind Aktualisierungsindikatoren für nicht teilnehmende Institute.
		if merkmal != "1":
			continue
		blz = line[0:8].strip()
		if not (blz.isdigit() and len(blz) == 8):
			continue
		bezeichnung = line[9:67].strip()
		plz = line[67:72].strip()
		ort = line[72:107].strip()
		bic = line[139:150].strip()
		yield {
			"blz": blz,
			"bank_name": bezeichnung,
			"bic": bic,
			"plz": plz,
			"ort": ort,
		}


def _upsert_rows(rows) -> dict[str, int]:
	"""Bulk-upsert: vorhandene BLZ-Einträge updaten, neue inserten.

	Wir nutzen einen einzigen INSERT ... ON DUPLICATE KEY UPDATE pro Batch
	für Geschwindigkeit (~6000 Einträge dauern ohne Bulk-Insert ewig).
	"""
	added = 0
	updated = 0
	skipped = 0
	# Existierende Einträge holen für Update vs Insert-Entscheidung.
	existing = set(frappe.db.get_all("BLZ Mapping", pluck="name") or [])

	for row in rows:
		blz = row["blz"]
		try:
			if blz in existing:
				frappe.db.set_value(
					"BLZ Mapping",
					blz,
					{
						"bank_name": row["bank_name"],
						"bic": row["bic"],
						"plz": row["plz"],
						"ort": row["ort"],
					},
				)
				updated += 1
			else:
				doc = frappe.new_doc("BLZ Mapping")
				doc.blz = blz
				doc.bank_name = row["bank_name"]
				doc.bic = row["bic"]
				doc.plz = row["plz"]
				doc.ort = row["ort"]
				doc.insert(ignore_permissions=True)
				added += 1
		except Exception:
			skipped += 1

	frappe.db.commit()
	return {"added": added, "updated": updated, "skipped": skipped}


def load_blz_data(url: str | None = None) -> dict[str, Any]:
	"""Auto-Loader: URL aus Settings oder Auto-Discovery, parsen, upsert.

	Wird vom Scheduler monatlich aufgerufen und kann auch manuell getriggert werden.
	"""
	resolved_url = (url or "").strip() or _settings_url() or find_blz_url()
	content = download_blz_file(resolved_url)
	rows = list(parse_blz_file(content))
	if not rows:
		raise BlzLoaderError(
			f"Keine validen BLZ-Einträge in Datei gefunden ({resolved_url})."
		)
	stats = _upsert_rows(rows)
	stats["url"] = resolved_url
	stats["total_parsed"] = len(rows)
	frappe.logger().info(f"BLZ-Datei geladen: {stats}")
	return stats


def extract_blz_from_iban(iban: str) -> str | None:
	"""DE-IBAN → 8-stellige BLZ (Stellen 5-12). Gibt None bei Nicht-DE/Invalid."""
	if not iban:
		return None
	cleaned = re.sub(r"\s+", "", iban).upper()
	if not cleaned.startswith("DE") or len(cleaned) != 22:
		return None
	blz = cleaned[4:12]
	return blz if blz.isdigit() else None


def extract_kontonummer_from_iban(iban: str) -> str | None:
	"""DE-IBAN → 10-stellige Kontonummer (Stellen 13-22)."""
	if not iban:
		return None
	cleaned = re.sub(r"\s+", "", iban).upper()
	if not cleaned.startswith("DE") or len(cleaned) != 22:
		return None
	return cleaned[12:22].lstrip("0") or "0"


def lookup_iban(iban: str) -> dict | None:
	"""Liefert {blz, bank_name, bic, plz, ort, kontonummer} oder None.

	None wenn keine DE-IBAN oder BLZ nicht in der Lookup-Tabelle.
	"""
	blz = extract_blz_from_iban(iban)
	if not blz:
		return None
	row = frappe.db.get_value(
		"BLZ Mapping",
		blz,
		["bank_name", "bic", "plz", "ort"],
		as_dict=True,
	)
	if not row:
		return None
	return {
		"blz": blz,
		"bank_name": row["bank_name"],
		"bic": row["bic"],
		"plz": row["plz"],
		"ort": row["ort"],
		"kontonummer": extract_kontonummer_from_iban(iban),
	}


@frappe.whitelist()
def reload_blz_data() -> dict:
	"""Whitelist-Endpoint zum manuellen Triggern aus dem Frontend / via UI-Button."""
	try:
		return load_blz_data()
	except BlzLoaderError as exc:
		frappe.throw(str(exc))
