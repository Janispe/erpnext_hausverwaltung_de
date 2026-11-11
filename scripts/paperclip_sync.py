#!/usr/bin/env python3
"""Import existing ERPNext problem references into Paperclip's backlog.

The default is a read-only preview. --demo uses synthetic cases without network
access. --apply journals each creation locally before sending it to Paperclip.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import json
import os
import shlex
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENDPOINT = "/api/method/hausverwaltung.hausverwaltung.agent_tools.paperclip_api.list_problem_cases"
ENV_KEYS = {
	"HV_URL",
	"HV_API_KEY",
	"HV_API_SECRET",
	"PAPERCLIP_URL",
	"PAPERCLIP_API_KEY",
	"PAPERCLIP_COMPANY_ID",
	"PAPERCLIP_PROJECT_ID",
	"PAPERCLIP_AGENT_ID",
}
SEVERITIES = {"Hinweis": "low", "Warnung": "medium", "Kritisch": "high"}
OPEN_STATUSES = {"Offen", "In Bearbeitung"}


class SyncError(Exception):
	"""An actionable failure whose message contains no credentials or HTTP bodies."""


def base_url(value: str) -> str:
	try:
		parts = urllib.parse.urlsplit(value)
	except ValueError:
		raise SyncError("Ungültige Basisadresse.") from None
	if (
		parts.scheme not in {"http", "https"}
		or not parts.hostname
		or parts.username is not None
		or parts.password is not None
		or parts.query
		or parts.fragment
		or any(character.isspace() for character in value)
	):
		raise SyncError("URL muss eine HTTP(S)-Basisadresse ohne Zugangsdaten, Query oder Fragment sein.")
	try:
		parts.port
	except ValueError:
		raise SyncError("Ungültiger URL-Port.") from None
	return urllib.parse.urlunsplit(
		(parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
	)


def load_environment(path: Path | None) -> dict[str, str]:
	values = {}
	if path:
		for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
			line = raw.strip()
			if not line or line.startswith("#"):
				continue
			key, separator, value = line.partition("=")
			key, value = key.strip(), value.strip()
			if not separator or key not in ENV_KEYS:
				raise SyncError(f"Ungültiger Konfigurationseintrag in Zeile {number}.")
			if value.startswith(("'", '"')):
				try:
					parts = shlex.split(value, comments=True)
				except ValueError:
					raise SyncError(f"Ungültige Anführungszeichen in Konfigurationszeile {number}.") from None
				if len(parts) != 1:
					raise SyncError(f"Ungültiger Wert in Konfigurationszeile {number}.")
				value = parts[0]
			values[key] = value
	values.update({key: os.environ[key] for key in ENV_KEYS if key in os.environ})
	return values


@dataclass(frozen=True)
class Config:
	hv_url: str
	paperclip_url: str
	company_id: str
	hv_authorization: str = field(repr=False)
	paperclip_authorization: str = field(repr=False)
	project_id: str = ""
	agent_id: str = ""

	@classmethod
	def from_environment(cls, values: dict[str, str]) -> Config:
		required = ENV_KEYS - {"PAPERCLIP_PROJECT_ID", "PAPERCLIP_AGENT_ID"}
		missing = sorted(key for key in required if not values.get(key))
		if missing:
			raise SyncError("Konfiguration fehlt: " + ", ".join(missing))
		if any("\n" in value or "\r" in value for value in values.values()):
			raise SyncError("Konfigurationswerte dürfen keine Zeilenumbrüche enthalten.")
		return cls(
			hv_url=base_url(values["HV_URL"]),
			paperclip_url=base_url(values["PAPERCLIP_URL"]),
			company_id=values["PAPERCLIP_COMPANY_ID"],
			hv_authorization=f"token {values['HV_API_KEY']}:{values['HV_API_SECRET']}",
			paperclip_authorization=f"Bearer {values['PAPERCLIP_API_KEY']}",
			project_id=values.get("PAPERCLIP_PROJECT_ID", ""),
			agent_id=values.get("PAPERCLIP_AGENT_ID", ""),
		)

	def binding(self) -> dict[str, str]:
		return {
			"hv_url": self.hv_url,
			"paperclip_url": self.paperclip_url,
			"company_id": self.company_id,
			"project_id": self.project_id,
		}


class NoRedirects(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		return None


class JsonClient:
	def __init__(self, url: str, authorization: str, service: str):
		self.url = url
		self.authorization = authorization
		self.service = service
		self.opener = urllib.request.build_opener(NoRedirects())

	def request(self, method: str, path: str, *, query=None, data=None) -> tuple[Any, Any]:
		url = self.url + path
		if query:
			url += "?" + urllib.parse.urlencode(query)
		request = urllib.request.Request(
			url,
			data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
			headers={
				"Authorization": self.authorization,
				"Accept": "application/json",
				"Content-Type": "application/json",
			},
			method=method,
		)
		try:
			with self.opener.open(request, timeout=30) as response:
				return json.load(response), response.headers
		except urllib.error.HTTPError as error:
			raise SyncError(
				f"{self.service}: HTTP {error.code} bei {method}. Basisadresse und Berechtigungen prüfen."
			) from None
		except (OSError, ValueError, http.client.HTTPException):
			raise SyncError(f"{self.service}: {method} fehlgeschlagen oder ungültige JSON-Antwort.") from None


def read_cases(client: JsonClient) -> list[dict[str, Any]]:
	cases = {}
	offset = 0
	while True:
		body, _headers = client.request("GET", ENDPOINT, query={"limit": 100, "offset": offset})
		page = body.get("message") if isinstance(body, dict) else None
		if not isinstance(page, dict) or not isinstance(page.get("cases"), list):
			raise SyncError("ERPNext: Unerwartete Antwort des Problem-Endpunkts.")
		for case in page["cases"]:
			if (
				not isinstance(case, dict)
				or not isinstance(case.get("name"), str)
				or not case["name"]
				or not isinstance(case.get("problem_key"), str)
				or not case["problem_key"]
				or not isinstance(case.get("status"), str)
				or case.get("status") not in OPEN_STATUSES
				or not isinstance(case.get("severity"), str)
				or case.get("severity") not in SEVERITIES
			):
				raise SyncError("ERPNext: Ungültiger Problembefund.")
			previous = cases.get(case["problem_key"])
			if previous and previous != case:
				raise SyncError(
					"ERPNext: Widersprüchlicher Befund während der Seitenabfrage. Leselauf wiederholen."
				)
			cases[case["problem_key"]] = case
		if page.get("has_more") is False:
			return list(cases.values())
		next_offset = page.get("next_offset")
		if page.get("has_more") is not True or type(next_offset) is not int or next_offset <= offset:
			raise SyncError("ERPNext: Ungültige Seitennavigation.")
		offset = next_offset


def make_payload(config: Config, case: dict[str, Any]) -> tuple[str, dict[str, Any]]:
	digest = hashlib.sha256(f"{config.hv_url}\0{case['problem_key']}".encode()).hexdigest()
	marker = f"hv-paperclip-{digest}"
	link = config.hv_url + "/desk/hausverwaltung-problem/" + urllib.parse.quote(case["name"], safe="")
	payload = {
		"title": f"ERP-Prüfung {case['name']} ({case['severity']})",
		"description": (
			f"[Fall in ERPNext öffnen]({link})\n\n"
			f"Fachstatus beim Import: {case['status']}\n\n"
			f"Schweregrad beim Import: {case['severity']}\n\n"
			"Aktuellen Sachstand im verlinkten ERPNext-Fall prüfen. Belegte Fakten, offene Fragen "
			"und den nächsten Prüfschritt für die zuständige Person zusammenstellen.\n\n"
			f"Importkennung: {marker}"
		),
		"status": "backlog",
		"priority": SEVERITIES[case["severity"]],
		"parentId": None,
		"idempotencyKey": marker,
	}
	if config.project_id:
		payload["projectId"] = config.project_id
	if config.agent_id:
		payload["assigneeAgentId"] = config.agent_id
	return marker, payload


def verify_issue(issue: Any, company: str, marker: str) -> dict[str, Any]:
	if (
		not isinstance(issue, dict)
		or not isinstance(issue.get("id"), str)
		or not issue["id"]
		or issue.get("companyId") != company
		or not isinstance(issue.get("description"), str)
		or f"Importkennung: {marker}" not in issue["description"].splitlines()
	):
		raise SyncError("Paperclip: Ticket gehört nicht eindeutig zu diesem ERPNext-Fall.")
	return issue


def find_issue(client: JsonClient, company: str, marker: str) -> dict[str, Any] | None:
	path = "/api/companies/" + urllib.parse.quote(company, safe="") + "/issues"
	matches = {}
	offset = 0
	while True:
		issues, headers = client.request("GET", path, query={"q": marker, "limit": 100, "offset": offset})
		if not isinstance(issues, list):
			raise SyncError("Paperclip: Unerwartete Ticketliste.")
		for issue in issues:
			if (
				isinstance(issue, dict)
				and isinstance(issue.get("description"), str)
				and f"Importkennung: {marker}" in issue["description"].splitlines()
			):
				issue = verify_issue(issue, company, marker)
				matches[issue["id"]] = issue
		if len(matches) > 1:
			raise SyncError(
				"Paperclip: Mehrere Tickets für denselben ERPNext-Fall. Zuordnung manuell klären."
			)
		has_more = headers.get("X-Paperclip-Has-More", "").lower()
		if has_more == "false" or (not has_more and len(issues) < 100):
			return next(iter(matches.values()), None)
		if has_more != "true":
			raise SyncError("Paperclip: Suchergebnis möglicherweise unvollständig. Import abgebrochen.")
		try:
			next_offset = int(headers["X-Paperclip-Next-Offset"])
		except (KeyError, ValueError):
			raise SyncError("Paperclip: Seitennavigation fehlt.") from None
		if next_offset <= offset:
			raise SyncError("Paperclip: Seitennavigation wiederholt dieselbe Seite.")
		offset = next_offset


def load_state(path: Path, config: Config) -> dict[str, Any]:
	if not path.exists():
		return {"version": 1, "binding": config.binding(), "issues": {}}
	try:
		state = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		raise SyncError("Statusdatei ist nicht lesbar oder beschädigt.") from None
	if (
		not isinstance(state, dict)
		or state.get("version") != 1
		or state.get("binding") != config.binding()
		or not isinstance(state.get("issues"), dict)
	):
		raise SyncError("Statusdatei gehört zu einer anderen Konfiguration oder hat ein ungültiges Format.")
	for entry in state["issues"].values():
		if (
			not isinstance(entry, dict)
			or entry.get("state") not in {"pending", "linked"}
			or (entry["state"] == "linked" and not isinstance(entry.get("issue_id"), str))
		):
			raise SyncError("Statusdatei enthält eine ungültige Ticketzuordnung.")
	return state


def save_state(path: Path, state: dict[str, Any]) -> None:
	with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
		temporary_path = Path(temporary.name)
		try:
			json.dump(state, temporary, ensure_ascii=False, indent=2)
			temporary.flush()
			os.fsync(temporary.fileno())
			os.replace(temporary_path, path)
		finally:
			temporary_path.unlink(missing_ok=True)
	directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
	try:
		os.fsync(directory_fd)
	finally:
		os.close(directory_fd)


@contextmanager
def state_lock(path: Path):
	path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
	with Path(str(path) + ".lock").open("a", encoding="utf-8") as lock:
		os.chmod(lock.name, 0o600)
		try:
			fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
		except BlockingIOError:
			raise SyncError("Für diese Statusdatei läuft bereits ein Import.") from None
		try:
			yield
		finally:
			fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def sync_cases(
	config: Config,
	cases: list[dict[str, Any]],
	client: JsonClient,
	state: dict[str, Any],
	state_path: Path,
	*,
	apply: bool,
) -> list[dict[str, Any]]:
	results = []
	for case in cases:
		marker, payload = make_payload(config, case)
		entry = state["issues"].get(marker)
		if entry and entry["state"] == "linked":
			issue, _headers = client.request(
				"GET", "/api/issues/" + urllib.parse.quote(entry["issue_id"], safe="")
			)
			issue = verify_issue(issue, config.company_id, marker)
		else:
			issue = find_issue(client, config.company_id, marker)
		if issue:
			if apply:
				state["issues"][marker] = {"state": "linked", "issue_id": issue["id"]}
				save_state(state_path, state)
			results.append({"problem": case["name"], "action": "existing", "issue_id": issue["id"]})
			continue
		if entry:
			raise SyncError(
				"Vorheriger Anlageversuch hat einen ungeklärten Ausgang. Ticket anhand der Importkennung "
				"in Paperclip prüfen und diesen Import erneut ausführen. Details stehen in der Pilot-Anleitung."
			)
		if not apply:
			results.append({"problem": case["name"], "action": "would_create", "payload": payload})
			continue
		state["issues"][marker] = {"state": "pending"}
		save_state(state_path, state)
		issue, _headers = client.request(
			"POST",
			"/api/companies/" + urllib.parse.quote(config.company_id, safe="") + "/issues",
			data=payload,
		)
		issue = verify_issue(issue, config.company_id, marker)
		state["issues"][marker] = {"state": "linked", "issue_id": issue["id"]}
		save_state(state_path, state)
		results.append({"problem": case["name"], "action": "created", "issue_id": issue["id"]})
	return results


def main(argv=None) -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--env-file", type=Path, help="Datei mit KEY=value, ohne Shell-Auswertung")
	parser.add_argument(
		"--state-file", type=Path, default=Path("~/.local/state/hausverwaltung/paperclip-pilot.json")
	)
	mode = parser.add_mutually_exclusive_group()
	mode.add_argument("--apply", action="store_true", help="Backlog-Tickets anlegen und Zuordnung speichern")
	mode.add_argument(
		"--demo", action="store_true", help="Synthetische Vorschau ohne Netzwerk oder Statusdatei"
	)
	args = parser.parse_args(argv)
	if args.demo:
		config = Config("https://erp.example.invalid", "http://127.0.0.1:3100", "demo-company", "", "")
		cases = [
			{"name": "PROB-DEMO-001", "problem_key": "HVP-demo-001", "status": "Offen", "severity": "Warnung"}
		]
		results = [
			{"problem": case["name"], "action": "would_create", "payload": make_payload(config, case)[1]}
			for case in cases
		]
	else:
		config = Config.from_environment(load_environment(args.env_file))
		state_path = args.state_file.expanduser().resolve()
		hv = JsonClient(config.hv_url, config.hv_authorization, "ERPNext")
		paperclip = JsonClient(config.paperclip_url, config.paperclip_authorization, "Paperclip")
		cases = read_cases(hv)
		if args.apply:
			with state_lock(state_path):
				results = sync_cases(
					config, cases, paperclip, load_state(state_path, config), state_path, apply=True
				)
		else:
			results = sync_cases(
				config, cases, paperclip, load_state(state_path, config), state_path, apply=False
			)
	print(
		json.dumps(
			{"mode": "apply" if args.apply else "preview", "cases": len(results), "results": results},
			ensure_ascii=False,
			indent=2,
		)
	)


if __name__ == "__main__":
	try:
		main()
	except SyncError as error:
		print(f"Paperclip-Import abgebrochen: {error}", file=sys.stderr)
		raise SystemExit(1) from None
	except OSError:
		print("Paperclip-Import abgebrochen: Lokale Datei nicht lesbar oder schreibbar.", file=sys.stderr)
		raise SystemExit(1) from None
