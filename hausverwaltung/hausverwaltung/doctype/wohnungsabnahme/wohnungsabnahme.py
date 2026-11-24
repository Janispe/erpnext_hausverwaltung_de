from __future__ import annotations

import base64
import json
import re
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation
from io import BytesIO

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate
from mail_merge.mail_merge.utils.pdf_engine import render_pdf
from PIL import Image, ImageOps, PngImagePlugin

DOCTYPE = "Wohnungsabnahme"
METER_TABLE = "zählerstand"
DIRECTIONS = {"Einzug", "Auszug"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS = 30
_SAVE = object()


class Wohnungsabnahme(Document):
	def validate(self):
		if self.flags.mobile_save is not _SAVE:
			frappe.throw(_("Bitte das Formular Wohnungsabnahme verwenden."))


def _contract(name, permission="read"):
	doc = frappe.get_doc("Mietvertrag", name)
	doc.check_permission(permission)
	if not doc.wohnung:
		frappe.throw(_("Dem Mietvertrag ist keine Wohnung zugeordnet."))
	frappe.get_doc("Wohnung", doc.wohnung).check_permission("read")
	return doc


def has_permission(doc, user=None):
	if not doc.mietvertrag or not doc.wohnung:
		return False
	if not frappe.has_permission("Mietvertrag", "read", doc=doc.mietvertrag, user=user):
		return False
	if not frappe.has_permission("Wohnung", "read", doc=doc.wohnung, user=user):
		return False
	return True


def no_generic_listing(user=None):
	return "1=0"


def _check_target(doc, permission="read"):
	contract = _contract(doc.mietvertrag, permission)
	if contract.wohnung != doc.wohnung or (permission == "write" and contract.docstatus == 2):
		frappe.throw(_("Wohnung und Mietvertrag passen nicht zusammen oder der Vertrag wurde storniert."))
	return contract


def _save(doc):
	doc.flags.mobile_save = _SAVE
	try:
		doc.save()
	finally:
		doc.flags.pop("mobile_save", None)


def _content(doc):
	return json.loads(doc.inhalt or '{"rooms":[],"keys":[],"meters":[]}')


def guard_attachment(file, method=None):
	current = file.get_doc_before_save()
	if file.flags.mobile_save is _SAVE:
		# Frappe grants File owners direct download access. Contract rights
		# should apply even after the employee who captured it loses access.
		file.owner = "Administrator"
	elif (
		file.attached_to_doctype == DOCTYPE
		or (current and current.attached_to_doctype == DOCTYPE)
		or (file.file_url and frappe.db.exists("File", {"file_url": file.file_url, "attached_to_doctype": DOCTYPE}))
	):
		frappe.throw(_("Bitte das Formular Wohnungsabnahme verwenden."), frappe.PermissionError)


def file_permission(doc, ptype=None, user=None):
	return doc.attached_to_doctype != DOCTYPE or ptype in {"read", "select"}


def _store_file(doc, filename, content):
	file = frappe.get_doc({
		"doctype": "File", "file_name": filename, "content": content, "is_private": 1,
		"attached_to_doctype": DOCTYPE, "attached_to_name": doc.name,
	})
	file.flags.mobile_save = _SAVE
	return file.insert(ignore_permissions=True)


def _private_file(name, doc):
	file = frappe.get_doc("File", name)
	if not (
		file.is_private and file.attached_to_doctype == DOCTYPE and file.attached_to_name == doc.name
	):
		frappe.throw(_("Die Datei gehört nicht zu dieser Wohnungsabnahme."), frappe.PermissionError)
	return file


def _view(doc):
	content = _content(doc)
	for room in content["rooms"]:
		room["photos"] = [
			{"url": _private_file(name, doc).file_url, "name": name} for name in room["photos"]
		]
	return {
		"name": doc.name,
		"termin": str(doc.termin),
		"stand": doc.stand,
		"protokoll": doc.protokoll,
		"klaerfall": doc.klaerfall,
		"paperless_link": doc.paperless_link,
		**content,
	}


@frappe.whitelist(methods=["GET"])
def load(mietvertrag: str, richtung: str, prozess: str | None = None):
	from .process import available_steps

	contract = _contract(mietvertrag)
	if richtung not in DIRECTIONS:
		frappe.throw(_("Einzug oder Auszug auswählen."))
	frappe.has_permission(DOCTYPE, "read", throw=True)
	name = frappe.db.get_value(DOCTYPE, {"mietvertrag": contract.name, "richtung": richtung}, "name")
	doc = frappe.get_doc(DOCTYPE, name) if name else None
	if doc:
		doc.check_permission("read")
		_check_target(doc)
	return {
		"vertrag": contract.name,
		"wohnung": contract.wohnung,
		"wohnung_label": frappe.db.get_value("Wohnung", contract.wohnung, "bezeichnung") or contract.wohnung,
		"termin": str((contract.von if richtung == "Einzug" else contract.bis) or nowdate()),
		"editable": contract.docstatus != 2 and contract.has_permission("write")
		and frappe.has_permission(DOCTYPE, "write", doc=doc),
		"draft": _view(doc) if doc else None,
		"steps": available_steps(contract, richtung, prozess),
	}


@frappe.whitelist(methods=["GET"])
def meters(mietvertrag: str, termin: str):
	contract = _contract(mietvertrag)
	frappe.has_permission(DOCTYPE, "read", throw=True)
	return _assigned_meters(contract.wohnung, _date(termin))


def _assigned_meters(wohnung, datum):
	# Use the same inclusive date bounds as the Wohnung device overview.
	return frappe.db.sql(
		"""
		SELECT DISTINCT z.name, z.zaehlernummer, z.zaehlerart, z.standort_beschreibung
		FROM `tabZaehler Zuordnung` AS zz
		INNER JOIN `tabZaehler` AS z ON z.name = zz.zaehler
		WHERE zz.bezugsobjekt_typ = 'Wohnung' AND zz.bezugsobjekt = %s
		  AND zz.docstatus < 2 AND zz.von <= %s AND (zz.bis IS NULL OR zz.bis >= %s)
		ORDER BY z.zaehlerart, z.zaehlernummer
		""",
		(wohnung, datum, datum),
		as_dict=True,
	)


def _date(value):
	try:
		return date.fromisoformat(value)
	except (TypeError, ValueError):
		frappe.throw(_("Ungültiges Datum."))


def _text(value, limit=200):
	if not isinstance(value, str) or len(value) > limit:
		frappe.throw(_("Ungültiger oder zu langer Text (maximal {0} Zeichen).").format(limit))
	return value.strip()


def _rows(data, key, limit):
	rows = data.get(key, [])
	if not isinstance(rows, list) or len(rows) > limit or not all(isinstance(row, dict) for row in rows):
		frappe.throw(_("Ungültige oder zu viele Einträge (maximal {0}).").format(limit))
	return rows


def _reading(value):
	try:
		number = Decimal(str(value).replace(",", "."))
		# The existing Frappe Float column stores up to nine fractional digits.
		if (
			not number.is_finite() or abs(number) >= 10**12
			or number != number.quantize(Decimal("0.000000001"))
			or number != Decimal(str(float(number)))
		):
			raise InvalidOperation
	except (DecimalException, ValueError):
		frappe.throw(_("Ungültiger Zählerstand."))
	return format(number.normalize(), "f") if number else "0"


def _normalise(doc, data):
	previous = {room["id"]: room["photos"] for room in _content(doc)["rooms"]}
	rooms = []
	seen = set()
	for row in _rows(data, "rooms", 60):
		key = row.get("id")
		if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,40}", key) or key in seen:
			frappe.throw(_("Ungültiger Raumschlüssel."))
		seen.add(key)
		rooms.append({
			"id": key, "label": _text(row.get("label", "")), "condition": _text(row.get("condition", ""), 4000),
			"defects": _text(row.get("defects", ""), 4000), "photos": previous.get(key, []),
		})
	if any(photos for key, photos in previous.items() if key not in seen):
		frappe.throw(_("Bitte zuerst die Fotos des zu löschenden Raums entfernen."))
	keys = []
	for row in _rows(data, "keys", 60):
		count = _text(str(row.get("count", "")), 6)
		if count and not re.fullmatch(r"[0-9]{1,6}", count):
			frappe.throw(_("Schlüsselanzahl muss eine ganze, nicht negative Zahl sein."))
		keys.append({"label": _text(row.get("label", "")), "count": int(count) if count else ""})
	readings = []
	for row in _rows(data, "meters", 100):
		value = row.get("value", "")
		datum = row.get("date", "")
		readings.append({
			"name": _text(row.get("name", "")),
			"date": str(_date(datum)) if datum else "",
			"value": "" if value == "" else _reading(value),
		})
	return {"rooms": rooms, "keys": keys, "meters": readings}


def _locked_draft(name, stand=None):
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	doc.check_permission("write")
	_check_target(doc, "write")
	if stand is not None and int(stand) != doc.stand and not doc.protokoll:
		frappe.throw(_("Der Entwurf wurde inzwischen geändert. Bitte laden Sie ihn neu."))
	return doc


def _editable(doc):
	if doc.protokoll:
		frappe.throw(_("Die Wohnungsabnahme ist bereits abgeschlossen."))


@frappe.whitelist(methods=["POST"])
def save_draft(mietvertrag: str, richtung: str, termin: str, inhalt: str, stand: int):
	frappe.has_permission(DOCTYPE, "write", throw=True)
	# Serialize the first creation too. A contract has one draft per direction.
	contract = frappe.get_doc("Mietvertrag", mietvertrag, for_update=True)
	contract.check_permission("write")
	if richtung not in DIRECTIONS:
		frappe.throw(_("Einzug oder Auszug auswählen."))
	name = frappe.db.get_value(
		DOCTYPE, {"mietvertrag": contract.name, "richtung": richtung}, "name", for_update=True
	)
	if name:
		doc = _locked_draft(name, stand)
		_editable(doc)
	else:
		doc = frappe.new_doc(DOCTYPE)
		doc.update({"mietvertrag": contract.name, "wohnung": contract.wohnung, "richtung": richtung, "stand": 0})
		_check_target(doc, "write")
	try:
		data = json.loads(inhalt)
	except (ValueError, TypeError):
		frappe.throw(_("Ungültige Erfassungsdaten."))
	if not isinstance(data, dict):
		frappe.throw(_("Ungültige Erfassungsdaten."))
	doc.inhalt = json.dumps(_normalise(doc, data), ensure_ascii=False)
	doc.termin = _date(termin)
	doc.stand += 1
	_save(doc)
	return _view(doc)


def _room(content, room_id):
	for room in content["rooms"]:
		if room["id"] == room_id:
			return room
	frappe.throw(_("Der Raum wurde nicht gefunden."))


def _photo_bytes(upload):
	raw = upload.stream.read(MAX_PHOTO_BYTES + 1)
	if len(raw) > MAX_PHOTO_BYTES:
		frappe.throw(_("Je Foto sind maximal 10 MB möglich."))
	try:
		with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as image:
			if image.width * image.height > 40_000_000:
				frappe.throw(_("Das Foto ist zu groß."))
			image = ImageOps.exif_transpose(image)
			image.thumbnail((1200, 1200))
			output = BytesIO()
			metadata = PngImagePlugin.PngInfo()
			# Keep identical photos in distinct permission scopes even when
			# Frappe deduplicates private attachments by content.
			metadata.add_text("Attachment", frappe.generate_hash(length=32))
			image = image.convert("RGB")
			image.info.clear()
			image.save(output, "PNG", pnginfo=metadata)
			return output.getvalue()
	except (OSError, ValueError, Image.DecompressionBombError):
		frappe.throw(_("Bitte ein gültiges JPEG-, PNG- oder WebP-Foto auswählen."))


@frappe.whitelist(methods=["POST"])
def upload_photo(name: str, stand: int, room_id: str):
	doc = _locked_draft(name, stand)
	_editable(doc)
	content = _content(doc)
	room = _room(content, room_id)
	if sum(len(item["photos"]) for item in content["rooms"]) >= MAX_PHOTOS:
		frappe.throw(_("Je Wohnungsabnahme sind maximal {0} Fotos möglich.").format(MAX_PHOTOS))
	upload = frappe.request.files.get("photo")
	if not upload:
		frappe.throw(_("Bitte ein Foto auswählen."))
	file = _store_file(doc, f"Abnahme-{doc.name}-Foto-{frappe.generate_hash(length=10)}.png", _photo_bytes(upload))
	room["photos"].append(file.name)
	doc.inhalt = json.dumps(content, ensure_ascii=False)
	doc.stand += 1
	_save(doc)
	return _view(doc)


@frappe.whitelist(methods=["POST"])
def remove_photo(name: str, stand: int, room_id: str, file_name: str):
	doc = _locked_draft(name, stand)
	_editable(doc)
	content = _content(doc)
	room = _room(content, room_id)
	if file_name not in room["photos"]:
		frappe.throw(_("Das Foto gehört nicht zu diesem Raum."), frappe.PermissionError)
	file = _private_file(file_name, doc)
	room["photos"].remove(file_name)
	doc.inhalt = json.dumps(content, ensure_ascii=False)
	doc.stand += 1
	_save(doc)
	view = _view(doc)
	# Frappe removes the blob before the File row. Restore it if this
	# transaction rolls back after deletion.
	file.flags.original_content = file.get_content(encodings=[])
	frappe.db.after_rollback.add(file.on_rollback)
	file.delete(ignore_permissions=True)
	return view


def _validate_completion(doc, content):
	if not content["rooms"] or any(not row["label"] or not row["condition"] for row in content["rooms"]):
		frappe.throw(_("Bitte mindestens einen Raum anlegen und je Raum Name und Zustand erfassen."))
	if any(not row["label"] or row["count"] == "" for row in content["keys"]):
		frappe.throw(_("Bitte je Schlüsselart Bezeichnung und Anzahl erfassen oder die leere Zeile entfernen."))
	assigned = {row.name: row for row in _assigned_meters(doc.wohnung, doc.termin)}
	present = set()
	by_date = {}
	for reading in content["meters"]:
		name, datum, value = reading["name"], reading["date"], reading["value"]
		if not name or not datum or value == "":
			frappe.throw(_("Bitte je Zähler Gerät, Ablesedatum und Wert erfassen."))
		if datum not in by_date:
			by_date[datum] = {row.name: row for row in _assigned_meters(doc.wohnung, datum)}
		if name not in by_date[datum]:
			frappe.throw(_("Zähler {0} war am {1} dieser Wohnung nicht zugeordnet.").format(name, datum))
		reading["device"] = by_date[datum][name]
		present.add(name)
	missing = assigned.keys() - present
	if missing:
		frappe.throw(_("Ablesung fehlt für Zähler {0}.").format(", ".join(sorted(assigned[n].zaehlernummer for n in missing))))


def _plan_readings(content):
	pending = []
	conflicts = []
	readings = sorted(content["meters"], key=lambda row: (row["name"], row["date"]))
	devices = {name: frappe.get_doc("Zaehler", name, for_update=True) for name in sorted({r["name"] for r in readings})}
	values = {}
	for reading in readings:
		name, datum, value = reading["name"], reading["date"], reading["value"]
		key = (name, datum)
		meter = devices[name]
		if key not in values:
			values[key] = {_reading(row.zaehlerstand) for row in meter.get(METER_TABLE) if str(row.datum) == datum}
		existing = values[key]
		if existing - {value}:
			conflicts.append(
				_("Zähler {0} am {1}: erfasst {2}, anderer Wert {3}.").format(
					reading["device"].zaehlernummer, datum, value, ", ".join(sorted(existing - {value}))
				)
			)
		elif not existing:
			pending.append((meter, datum, value))
			existing.add(value)
	return pending, conflicts


def _create_pdf(doc, content):
	for room in content["rooms"]:
		room["images"] = [
			base64.b64encode(_private_file(name, doc).get_content(encodings=[])).decode("ascii")
			for name in room["photos"]
		]
	html = frappe.render_template("templates/wohnungsabnahme_protokoll.html", {
		"doc": doc, "content": content,
		"wohnung": frappe.db.get_value("Wohnung", doc.wohnung, "bezeichnung") or doc.wohnung,
	})
	pdf = render_pdf(html)
	return _store_file(doc, f"Abnahme-{doc.richtung}-{doc.name}.pdf", pdf)


@frappe.whitelist(methods=["POST"])
def complete(name: str, stand: int):
	doc = _locked_draft(name, stand)
	if doc.protokoll:
		return _view(doc)
	content = _content(doc)
	_validate_completion(doc, content)
	pending, conflicts = _plan_readings(content)
	if conflicts:
		doc.klaerfall = "\n".join(conflicts)
	else:
		doc.protokoll = _create_pdf(doc, content).file_url
		doc.klaerfall = ""
		for meter, datum, value in pending:
			meter.append(METER_TABLE, {"datum": datum, "zaehlerstand": value})
		for meter in {meter.name: meter for meter, _, _ in pending}.values():
			# Scoped to a validated Wohnung assignment. This workflow does not grant
			# general edit rights to the meter master data.
			meter.save(ignore_permissions=True)
	doc.stand += 1
	_save(doc)
	return _view(doc)
