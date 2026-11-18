# Vorschlagsengine im Produktivsystem (OpenClaw / MCP)

Mit dieser Konfiguration kann ein angebundener OpenClaw-Agent über FAC/MCP strukturierte
Dokumentvorschläge (`hv.doc.create/v1`, `hv.doc.update/v1`, `hv.doc.submit/v1`) einreichen,
einsehen und überarbeiten. Die Prüfung, Freigabe und Ausführung erfolgen ausschließlich durch einen
Menschen im Desk unter `/app/hv-proposals` mit dessen eigenen ERPNext-Rechten.

## 1. Produktive Aktivierung (getrennt vom synthetischen Piloten)

Auf dem Produktivsystem **nur** `hv_proposals_enabled` aktivieren; `hv_proposals_synthetic_enabled`
bleibt deaktiviert:

```bash
bench --site <site> migrate
bench --site <site> set-config --parse hv_proposals_enabled True
```

Anschließend die Web-Worker neu laden (`HUP` / Neustart), damit `site_config.json` aktiv wird.

## 2. Rollen und OpenClaw-Werkzeuge freischalten

- **OpenClaw-API-Benutzer:** erhält die Rolle `Agent Readonly API` (plus Leserechte für die
  gewünschten Fach-DocTypes) und `HV Proposal Agent`. Er darf **nicht** `HV Proposal Reviewer`
  besitzen.
- **Menschliche Prüfer:** erhalten die Rolle `HV Proposal Reviewer` (**ohne** `HV Proposal Agent`)
  sowie ihre regulären ERPNext-Rechte (`create`/`write`/`submit`) für die jeweiligen Fach-DocTypes.

Für den OpenClaw-API-Benutzer die FAC-Werkzeuge inklusive Vorschlags-Opt-in aktivieren:

```bash
bench --site <site> execute \
  hausverwaltung.hausverwaltung.services.fac_setup.enable_external_tools \
  --kwargs '{"user":"OPENCLAW-API-BENUTZER","include_focused_tools":true,"include_proposal_tools":true}'
```

Danach in OpenClaw eine neue Sitzung starten bzw. `tools/list` neu laden. Angeboten werden
ausschließlich:

- `hv_proposal_submit_doc` (Anlegen, Ändern oder Einreichen vorschlagen)
- `hv_proposal_revise_doc` (Überarbeitete Revision nach Rückfrage oder Veraltung)
- `hv_proposal_list_packages`, `hv_proposal_get_package`, `hv_proposal_get`, `hv_proposal_audit`

Werkzeuge zum Freigeben oder Ausführen werden OpenClaw nicht angeboten.

## 3. Sicherheitsgrenzen

- System-, Rechte-, Einstellungs-, Datei-, Skript- und Vorschlags-DocTypes (`User`, `Role`,
  `Has Role`, `User Permission`, `Custom DocPerm`, `Server Script`, `Client Script`,
  `Assistant Core Settings`, `FAC Tool Configuration`, `HV Action Proposal`, usw.) sowie
  Systemmodule (`Core`, `Custom`, `Workflow`, `Automation`, …) sind gesperrt.
- `hv.doc.update/v1` und `hv.doc.submit/v1` speichern beim Einreichen einen Ausgangs-Snapshot;
  wird das Dokument zwischenzeitlich geändert, wird der Vorschlag beim Prüfen oder Ausführen
  automatisch `Stale`.
- `hv.doc.create/v1`, `hv.doc.update/v1` und `hv.doc.submit/v1` werden ausschließlich durch eine
  echte menschliche Browser-Sitzung (`HV Proposal Reviewer` ohne `HV Proposal Agent`) ausgeführt.
