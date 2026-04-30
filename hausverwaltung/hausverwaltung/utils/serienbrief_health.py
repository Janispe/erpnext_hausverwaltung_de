"""Read-only Audit für ``Serienbrief Vorlage``-Records.

Findet drei typische Importer-Artefakte:

1. **Unaufgelöste Word-Mergefield-Tokens** wie ``«Whg-Art»`` — kommen vor, wenn
   der WinCASA→Frappe-Importer einen Token nicht in Frappe-Jinja umgewandelt
   hat (z.B. weil das Token im Word-HTML über ``<span>``-Tags zerteilt war).
2. **Mojibake-Tokens** (``Â«…Â»``) — UTF-8/Latin-1-Konvertierungsfehler.
3. **Doppelte Anrede** — wenn sowohl Literal-Text "Sehr geehrter Herr X,"
   als auch ``{{ baustein("MieterAnredeNameAlle") }}`` im Content stehen.

Alle Checks sind reine Read-Only-Lookups, ohne Seiteneffekt.
"""

from __future__ import annotations

import re

import frappe

from hausverwaltung.hausverwaltung.data_import.placeholder_mapping import (
	PLACEHOLDER_MAPPING,
	_normalize_word_tokens,
)


_TOKEN_RE = re.compile(r"«([^»]+?)»", re.DOTALL)
_MOJIBAKE_TOKEN_RE = re.compile(r"Â«([^»]+?)Â»", re.DOTALL)
_ANREDE_BAUSTEIN = '{{ baustein("MieterAnredeNameAlle") }}'
_LITERAL_ANREDE_RE = re.compile(
	r"<p[^>]*>\s*(?:&nbsp;|\s)*"
	r"Sehr\s+geehrte[rs]?\s+[^<]{0,200}?</p>",
	re.IGNORECASE | re.DOTALL,
)

# Bekannte falsche Jinja-Field-Referenzen (Doctype hat das Feld nicht).
# Format: regex → human-readable label.
_BROKEN_JINJA_PATTERNS = [
	(re.compile(r"\{\{\s*wohnung\.art\s*\}\}"), "wohnung.art (Field existiert nicht)"),
	(re.compile(r"\{\{\s*wohnung\.nummer\s*\}\}"), "wohnung.nummer (Field existiert nicht)"),
]


def _scan(content: str) -> dict:
	"""Analysiert einen ``content``-String und gibt Symptom-Liste zurück."""
	if not content:
		return {"issues": [], "unmapped_tokens": []}

	# Tokens NACH HTML-Tag-Bereinigung extrahieren (sonst sehen wir nur die
	# Span-Fragmente, nicht die echten Token-Namen).
	cleaned = _normalize_word_tokens(content)

	issues: list[str] = []
	unmapped_tokens: list[str] = []

	# 1) Unaufgelöste «…»-Tokens
	tokens = {m.group(1).strip() for m in _TOKEN_RE.finditer(cleaned)}
	if tokens:
		issues.append("unresolved_word_tokens")
		for tok in sorted(tokens):
			if tok in PLACEHOLDER_MAPPING:
				continue  # Wird beim Re-Run gemappt
			unmapped_tokens.append(tok)

	# 2) Mojibake
	if _MOJIBAKE_TOKEN_RE.search(content):
		issues.append("mojibake_tokens")

	# 3) Doppelte Anrede: Anrede-Baustein-Token + Literal-Sehr-geehrte
	if _ANREDE_BAUSTEIN in content and _LITERAL_ANREDE_RE.search(content):
		issues.append("duplicate_salutation")

	# 4) Token-Suffix-Reste à la "{{ vorauszahlung_1 }}_Netto"
	if re.search(r"\}\}\s*_[A-Z][a-z]+", content):
		issues.append("token_suffix_residue")

	# 5) Bekannte kaputte Jinja-Field-Referenzen
	broken = [label for regex, label in _BROKEN_JINJA_PATTERNS if regex.search(content)]
	if broken:
		issues.append("broken_jinja_field_refs")
		unmapped_tokens.extend(broken)

	return {"issues": issues, "unmapped_tokens": unmapped_tokens}


@frappe.whitelist()
def audit_templates(verbose: int | bool = False) -> dict:
	"""Audit aller ``Serienbrief Vorlage``-Records.

	Returns:
		Dict mit ``total``, ``with_issues``, ``records`` (Liste pro Vorlage
		mit Problemen) und ``unmapped_token_summary`` (alle ungemappten
		Tokens gruppiert nach Häufigkeit).
	"""
	verbose = bool(int(verbose)) if isinstance(verbose, str) else bool(verbose)

	rows = frappe.get_all(
		"Serienbrief Vorlage",
		fields=["name", "content"],
		order_by="name",
	)

	with_issues: list[dict] = []
	all_unmapped: dict[str, int] = {}

	for row in rows:
		report = _scan(row.get("content") or "")
		if not report["issues"]:
			continue
		entry = {
			"name": row["name"],
			"issues": report["issues"],
			"unmapped_tokens": report["unmapped_tokens"],
		}
		with_issues.append(entry)
		for tok in report["unmapped_tokens"]:
			all_unmapped[tok] = all_unmapped.get(tok, 0) + 1

	summary = {
		"total": len(rows),
		"with_issues": len(with_issues),
		"records": with_issues,
		"unmapped_token_summary": dict(
			sorted(all_unmapped.items(), key=lambda kv: -kv[1])
		),
	}

	if verbose:
		print(f"\n=== Serienbrief Vorlage Audit ===")
		print(f"  Total: {summary['total']}")
		print(f"  Mit Problemen: {summary['with_issues']}")
		if summary["records"]:
			print("\n  Probleme pro Vorlage:")
			for r in summary["records"]:
				toks = (
					f" — ungemappte Tokens: {r['unmapped_tokens']}"
					if r["unmapped_tokens"]
					else ""
				)
				print(f"    - {r['name']}: {r['issues']}{toks}")
		if summary["unmapped_token_summary"]:
			print("\n  Tokens ohne Mapping (sortiert nach Häufigkeit):")
			for tok, count in summary["unmapped_token_summary"].items():
				print(f"    - {tok!r} (in {count} Vorlage[n])")

	return summary
