"""Sammel-PDFs in einzelne Rechnungsdateien zerlegen.

Die Erkennung nutzt Rechnungsnummern und explizite Seitenzaehler. Falls ein
Sammel-PDF keinerlei solche Merkmale enthaelt, wird bewusst auf "eine Rechnung
pro Seite" zurueckgefallen. Dieser Fallback ist nur ueber den ausdruecklichen
Sammel-PDF-Schalter im Frontend erreichbar.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path
from typing import Any

import frappe
from frappe.utils.file_manager import get_file

MAX_PDF_PAGES = 500

_PAGE_NUMBER_PATTERNS = (
	re.compile(r"\bseite\s+(\d{1,4})\s+(?:von|/|\|)\s*(\d{1,4})\b", re.IGNORECASE),
	re.compile(r"\bpage\s+(\d{1,4})\s+(?:of|/)\s*(\d{1,4})\b", re.IGNORECASE),
	re.compile(r"\bseite\s+(\d{1,4})\b", re.IGNORECASE),
)
_INVOICE_NUMBER_PATTERNS = (
	re.compile(
		r"\brechnungs(?:nummer|nr\.?|[- ]?nr\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9./_-]{2,})",
		re.IGNORECASE,
	),
	re.compile(
		r"\brechnung\s*(?:nr\.?|nummer)\s*[:#]?\s*([A-Z0-9][A-Z0-9./_-]{2,})",
		re.IGNORECASE,
	),
	re.compile(r"\bbelegnummer\s*[:#]?\s*([A-Z0-9][A-Z0-9./_-]{2,})", re.IGNORECASE),
)


def _page_number(text: str) -> tuple[int | None, int | None]:
	for pattern in _PAGE_NUMBER_PATTERNS:
		match = pattern.search(text or "")
		if not match:
			continue
		current = int(match.group(1))
		total = int(match.group(2)) if match.lastindex and match.lastindex >= 2 else None
		if current < 1 or (total is not None and (total < current or total > MAX_PDF_PAGES)):
			continue
		return current, total
	return None, None


def _invoice_number(text: str) -> str | None:
	# Kopfbereich reicht normalerweise aus und verhindert Treffer in langen
	# Positionsbeschreibungen oder angehaengten Leistungsnachweisen.
	header = (text or "")[:5000]
	for pattern in _INVOICE_NUMBER_PATTERNS:
		match = pattern.search(header)
		if not match:
			continue
		value = match.group(1).strip(" .:/#-")
		if value and any(char.isdigit() for char in value):
			return value.upper()
	return None


def detect_invoice_groups(page_texts: list[str]) -> tuple[list[dict[str, Any]], str | None]:
	"""Liefert erkannte Rechnungsgruppen mit nullbasierten Seitengrenzen."""
	if not page_texts:
		return [], None

	page_info = []
	for text in page_texts:
		page_no, page_total = _page_number(text)
		page_info.append({
			"invoice_number": _invoice_number(text),
			"page_number": page_no,
			"page_total": page_total,
		})

	groups: list[dict[str, Any]] = []
	start = 0
	group_invoice_number = page_info[0]["invoice_number"]

	def finish(end: int) -> None:
		groups.append({
			"start": start,
			"end": end,
			"invoice_number": group_invoice_number,
		})

	for index in range(1, len(page_info)):
		previous = page_info[index - 1]
		current = page_info[index]
		current_number = current["invoice_number"]
		starts_new = False

		# Ein explizites Zurueckspringen auf Seite 1 ist das staerkste Signal.
		if current["page_number"] == 1:
			starts_new = True
		# Nach der letzten Seite einer Rechnung beginnt die naechste Seite neu.
		elif (
			previous["page_number"] is not None
			and previous["page_total"] is not None
			and previous["page_number"] >= previous["page_total"]
		):
			starts_new = True
		# Geaenderte Rechnungsnummer = neue Rechnung. Eine Nummer, die erstmals
		# mitten im Dokument auftaucht, markiert ebenfalls einen neuen Anfang.
		elif current_number and current_number != group_invoice_number:
			starts_new = True

		if starts_new:
			finish(index - 1)
			start = index
			group_invoice_number = current_number
		elif group_invoice_number is None and current_number:
			group_invoice_number = current_number

	finish(len(page_info) - 1)

	has_complete_page_sequence = all(
		info["page_number"] == index
		and info["page_total"] == len(page_info)
		for index, info in enumerate(page_info, start=1)
	)
	if len(groups) == 1 and len(page_texts) > 1 and not has_complete_page_sequence:
		groups = [
			{"start": index, "end": index, "invoice_number": info["invoice_number"]}
			for index, info in enumerate(page_info)
		]
		return groups, (
			"Es wurden keine sicheren Rechnungsgrenzen erkannt; deshalb wurde jede Seite als eigene Rechnung behandelt."
		)

	return groups, None


def _extract_page_texts(reader) -> list[str]:
	texts: list[str] = []
	for page in reader.pages:
		try:
			texts.append(page.extract_text() or "")
		except Exception:
			texts.append("")
	return texts


def _page_position_tokens(
	value: str | list[int] | tuple[int, ...] | None,
) -> list[str]:
	if value is None or value == "":
		return []
	if isinstance(value, (list, tuple)):
		return [str(item).strip() for item in value]
	return [token for token in re.split(r"[,;\s]+", str(value).strip()) if token]


def _parse_page_positions(
	value: str | list[int] | tuple[int, ...] | None,
	page_count: int,
	*,
	allow_negative: bool = False,
) -> list[int]:
	tokens = _page_position_tokens(value)

	excluded: set[int] = set()
	for token in tokens:
		if allow_negative and re.fullmatch(r"-\d+", token):
			position = page_count + int(token)
			if position < 0 or position >= page_count:
				frappe.throw(
					f"Seitenposition '{token}' liegt ausserhalb eines Blocks mit {page_count} Seiten."
				)
			excluded.add(position)
			continue
		match = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
		if not match:
			examples = "3, 6, 9-11 oder -1" if allow_negative else "3, 6 oder 9-11"
			frappe.throw(f"Ungueltige Seitenangabe '{token}'. Erlaubt sind Angaben wie {examples}.")
		start = int(match.group(1))
		end = int(match.group(2) or start)
		if start < 1 or end < start or end > page_count:
			frappe.throw(
				f"Seitenangabe '{token}' liegt ausserhalb des PDFs mit {page_count} Seiten."
			)
		excluded.update(range(start - 1, end))

	if len(excluded) >= page_count:
		if allow_negative:
			frappe.throw("Es koennen nicht alle Seitenpositionen eines Rechnungsblocks ausgeschlossen werden.")
		frappe.throw("Es koennen nicht alle Seiten des PDFs ausgeschlossen werden.")
	return sorted(excluded)


def parse_excluded_pages(value: str | list[int] | tuple[int, ...] | None, page_count: int) -> list[int]:
	"""Parst 1-basierte Angaben wie ``3, 6, 9-11`` zu 0-basierten Seiten."""
	return _parse_page_positions(value, page_count)


def parse_repeated_page_positions(
	value: str | list[int] | tuple[int, ...] | None,
	page_count: int,
) -> list[int]:
	"""Parst Positionen innerhalb eines Blocks; ``-1`` bezeichnet die letzte Seite."""
	return _parse_page_positions(value, page_count, allow_negative=True)


def split_pdf_bytes(
	content: bytes,
	pages_per_invoice: int | str = 0,
	excluded_pages: str | list[int] | tuple[int, ...] | None = None,
	excluded_page_positions: str | list[int] | tuple[int, ...] | None = None,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
	"""Zerlegt PDF-Bytes und liefert Bytes + Metadaten je Rechnung."""
	try:
		from pypdf import PdfReader, PdfWriter
	except ImportError:
		from PyPDF2 import PdfReader, PdfWriter

	try:
		reader = PdfReader(io.BytesIO(content))
		if getattr(reader, "is_encrypted", False):
			try:
				decrypted = reader.decrypt("")
			except Exception:
				frappe.throw("Das PDF ist passwortgeschuetzt und kann nicht aufgeteilt werden.")
			if not decrypted:
				frappe.throw("Das PDF ist passwortgeschuetzt und kann nicht aufgeteilt werden.")
		page_count = len(reader.pages)
	except Exception as exc:
		frappe.throw(f"Das hochgeladene PDF konnte nicht gelesen werden: {exc}")

	if not page_count:
		frappe.throw("Das PDF enthaelt keine Seiten.")
	if page_count > MAX_PDF_PAGES:
		frappe.throw(f"Das PDF hat {page_count} Seiten; maximal erlaubt sind {MAX_PDF_PAGES}.")

	try:
		fixed_page_count = int(pages_per_invoice or 0)
	except (TypeError, ValueError):
		frappe.throw("Seiten pro Rechnung muss eine ganze Zahl sein.")
	if fixed_page_count < 0 or fixed_page_count > MAX_PDF_PAGES:
		frappe.throw(f"Seiten pro Rechnung muss 0 oder eine Zahl bis {MAX_PDF_PAGES} sein.")

	page_texts = _extract_page_texts(reader)
	excluded_indexes = parse_excluded_pages(excluded_pages, page_count)
	excluded_set = set(excluded_indexes)
	included_indexes = [index for index in range(page_count) if index not in excluded_set]
	included_texts = [page_texts[index] for index in included_indexes]
	repeated_excluded_positions: list[int] = []
	repeated_excluded_indexes: list[int] = []
	repeated_position_tokens = _page_position_tokens(excluded_page_positions)
	has_repeated_exclusions = bool(repeated_position_tokens)
	repeated_positive_positions: list[int] = []
	repeated_negative_offsets: list[int] = []
	if has_repeated_exclusions:
		if not fixed_page_count:
			frappe.throw(
				"Seiten innerhalb jeder Rechnung koennen nur mit einer festen Anzahl Seiten pro Rechnung ausgeschlossen werden."
			)
		repeated_excluded_positions = parse_repeated_page_positions(
			excluded_page_positions,
			fixed_page_count,
		)
		positive_tokens = [
			token for token in repeated_position_tokens if not re.fullmatch(r"-\d+", token)
		]
		repeated_positive_positions = _parse_page_positions(
			",".join(positive_tokens),
			fixed_page_count,
		)
		repeated_negative_offsets = [
			int(token) for token in repeated_position_tokens if re.fullmatch(r"-\d+", token)
		]
	if fixed_page_count:
		groups = []
		empty_blocks = 0
		for start in range(0, len(included_indexes), fixed_page_count):
			block_indexes = included_indexes[start : start + fixed_page_count]
			block_excluded_positions = set(repeated_positive_positions)
			# Negative Angaben beziehen sich auf das tatsaechliche Blockende,
			# auch wenn der letzte Block weniger Seiten als konfiguriert hat.
			for offset in repeated_negative_offsets:
				position = len(block_indexes) + offset
				if position >= 0:
					block_excluded_positions.add(position)
			page_indexes = []
			for position, page_index in enumerate(block_indexes):
				if position in block_excluded_positions:
					repeated_excluded_indexes.append(page_index)
				else:
					page_indexes.append(page_index)
			if not page_indexes:
				empty_blocks += 1
				continue
			groups.append({
				"start": page_indexes[0],
				"end": page_indexes[-1],
				"page_indexes": page_indexes,
				"invoice_number": _invoice_number(page_texts[page_indexes[0]]),
			})
		remainder = len(included_indexes) % fixed_page_count
		warnings = []
		if remainder:
			warnings.append(
				f"Die letzte Rechnung enthaelt nur {remainder} statt {fixed_page_count} Seiten. "
				"Bitte diese letzte Datei pruefen."
			)
		if empty_blocks:
			warnings.append(
				f"{empty_blocks} Rechnungsblock/-bloecke enthielten nach dem Ausschluss keine Seite und wurden ausgelassen."
			)
		warning = " ".join(warnings) or None
		if not groups:
			frappe.throw("Nach den Seitenausschluessen bleibt keine Rechnung uebrig.")
	else:
		detected_groups, warning = detect_invoice_groups(included_texts)
		groups = []
		for group in detected_groups:
			page_indexes = included_indexes[group["start"] : group["end"] + 1]
			groups.append({
				"start": page_indexes[0],
				"end": page_indexes[-1],
				"page_indexes": page_indexes,
				"invoice_number": group.get("invoice_number"),
			})
	parts: list[dict[str, Any]] = []
	for group in groups:
		writer = PdfWriter()
		page_indexes = group["page_indexes"]
		for page_index in page_indexes:
			writer.add_page(reader.pages[page_index])
		buffer = io.BytesIO()
		writer.write(buffer)
		parts.append({
			**group,
			"content": buffer.getvalue(),
			"page_count": len(page_indexes),
			"source_pages": [page_index + 1 for page_index in page_indexes],
		})
	return parts, warning, {
		"source_page_count": page_count,
		"included_page_count": sum(part["page_count"] for part in parts),
		"excluded_pages": [page_index + 1 for page_index in excluded_indexes],
		"excluded_page_positions": [position + 1 for position in repeated_excluded_positions],
		"repeated_excluded_pages": [page_index + 1 for page_index in repeated_excluded_indexes],
		"excluded_page_count": len(excluded_indexes) + len(repeated_excluded_indexes),
	}


def _safe_invoice_label(value: str | None) -> str:
	if not value:
		return ""
	label = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
	return label[:48]


def _store_private_pdf(content: bytes, filename: str) -> dict[str, Any]:
	"""Speichert PDF-Bytes ohne Frappes fehlerhaften Binary-Re-Encode-Pfad."""
	from frappe.core.doctype.file.utils import generate_file_name
	from frappe.utils.file_manager import get_files_path

	content_hash = hashlib.sha1(content).hexdigest()
	existing = frappe.db.get_value(
		"File",
		{"content_hash": content_hash},
		["name", "file_url", "file_name"],
		as_dict=True,
	)
	if existing:
		return {
			"doctype": "File",
			"file_url": existing.file_url,
			"file_name": existing.file_name,
			"is_new_file": False,
		}

	target_dir = get_files_path(is_private=1)
	frappe.create_folder(target_dir)
	safe_name = generate_file_name(name=filename, suffix=content_hash[-6:], is_private=True)
	full_path = os.path.join(target_dir, safe_name)
	with open(full_path, "wb") as output:
		output.write(content)

	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": safe_name,
		"file_url": f"/private/files/{safe_name}",
		"is_private": 1,
		"file_size": len(content),
		"content_hash": content_hash,
		"folder": "Home",
	})
	file_doc.flags.copy_from_existing_file = True
	file_doc.flags.ignore_permissions = True
	file_doc.insert()
	return {
		"doctype": "File",
		"file_url": file_doc.file_url,
		"file_name": file_doc.file_name,
		"is_new_file": True,
	}


def _lookup_vorschlag(file_url: str) -> dict[str, Any] | None:
	rows = frappe.get_all(
		"Buchungs Vorschlag",
		filters={"file_url": file_url},
		fields=[
			"name",
			"status",
			"linked_purchase_invoice",
			"session_id",
			"original_filename",
			"error_message",
		],
		order_by="creation desc",
		limit_page_length=1,
	)
	return dict(rows[0]) if rows else None


@frappe.whitelist()
def split_invoice_pdf(
	file_url: str,
	pages_per_invoice: int | str = 0,
	excluded_pages: str | None = None,
	excluded_page_positions: str | None = None,
) -> dict[str, Any]:
	"""Teilt eine zuvor hochgeladene private PDF in einzelne File-Dokumente."""
	file_url = (file_url or "").strip()
	if not file_url:
		frappe.throw("Bitte zuerst eine PDF-Datei hochladen.")

	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw("Die hochgeladene Datei wurde nicht gefunden.")
	frappe.get_doc("File", file_name).check_permission("read")

	try:
		source_filename, content = get_file(file_url)
	except Exception as exc:
		frappe.throw(f"Die hochgeladene Datei konnte nicht geladen werden: {exc}")
	if isinstance(content, str):
		content = content.encode("latin-1", errors="replace")
	if not content.startswith(b"%PDF"):
		frappe.throw("Die hochgeladene Datei ist kein gueltiges PDF.")

	parts, warning, split_meta = split_pdf_bytes(
		content,
		pages_per_invoice=pages_per_invoice,
		excluded_pages=excluded_pages,
		excluded_page_positions=excluded_page_positions,
	)
	stem = Path(source_filename or "sammelrechnung.pdf").stem[:80]
	files = []
	for index, part in enumerate(parts, start=1):
		invoice_label = _safe_invoice_label(part.get("invoice_number"))
		label_suffix = f"_{invoice_label}" if invoice_label else ""
		filename = f"{stem}_rechnung_{index:03d}{label_suffix}.pdf"
		file_data = _store_private_pdf(part["content"], filename)
		file_data.update({
			"page_from": part["start"] + 1,
			"page_to": part["end"] + 1,
			"page_count": part["page_count"],
			"source_pages": part["source_pages"],
			"invoice_number": part.get("invoice_number") or "",
		})
		file_data["existing_vorschlag"] = _lookup_vorschlag(file_data["file_url"])
		files.append(file_data)

	return {
		"source_file_url": file_url,
		"source_page_count": split_meta["source_page_count"],
		"included_page_count": split_meta["included_page_count"],
		"excluded_pages": split_meta["excluded_pages"],
		"excluded_page_positions": split_meta["excluded_page_positions"],
		"repeated_excluded_pages": split_meta["repeated_excluded_pages"],
		"excluded_page_count": split_meta["excluded_page_count"],
		"count": len(files),
		"files": files,
		"warning": warning,
		"pages_per_invoice": int(pages_per_invoice or 0),
	}
