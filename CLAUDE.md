# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo-Kontext

Dies ist die **Frappe-App `hausverwaltung`** für Mietverträge, Betriebskosten-Abrechnung, Bankabgleich, Mahnwesen und Serienbriefe. Sie lebt unter `apps/hausverwaltung/` innerhalb eines `frappe_docker`-Setups.

Es existiert eine **zweite, private Companion-App `hausverwaltung_peters`** unter `apps/hausverwaltung_peters/` (eigenes Git-Repo, `required_apps = ["hausverwaltung"]`). Sie enthält:

- Einmal-Importer (`migration/real_import/` — WinCASA → Frappe)
- Destruktive Cleanup-Helper (`migration/delete_all.py`)
- Peters-spezifische Patches & Print-Format-/Serienbrief-Vorlagen-Setup
- Docker Compose Stack (`compose.yml`) — der Hauptstack lebt hier, nicht in der public App

**Wichtige Importregel:** Public-App-Code darf **niemals** aus `hausverwaltung_peters.*` importieren. Wenn eine Funktion auf beiden Seiten gebraucht wird, **extrahiere** sie nach `hausverwaltung/hausverwaltung/utils/` oder `data_import/`. Bestehende Extraktionen:

| Was | Ziel-Modul |
|---|---|
| Customer-Anlage (`build_customer_id`, `get_or_create_customer`) | `hausverwaltung.hausverwaltung.utils.customer` |
| Festbetrag-Upsert + Mietvertrag-Zeitraum-Matching | `hausverwaltung.hausverwaltung.utils.festbetrag` |
| Generic CoA-Importer (ERPNext-Wrapper) | `hausverwaltung.hausverwaltung.data_import.coa_importer` |

Public Patches (`patches.txt`) dürfen nur `utils.*` referenzieren, **nicht** `real_import.*` oder `delete_all`.

## Setup & Umgebung

Der laufende Stack ist **`apps/hausverwaltung_peters/compose.yml`** (nicht `compose.yaml` im Repo-Root). Container-Naming-Schema: `hausverwaltung_peters-<service>-1`.

- **Site-Name:** `frontend` (so heißen alle `bench --site …` Aufrufe)
- **Backend-Container:** `hausverwaltung_peters-backend-1`
- **Frontend-URL (Caddy):** lokal `http://localhost:8080` / Tailscale `http://100.89.21.12:8080`
- **Temporal UI:** `http://localhost:8081`

Public App ist als Volume gemounted: `../hausverwaltung:/home/frappe/frappe-bench/apps/hausverwaltung` — Code-Änderungen im Repo wirken nach Worker-Restart sofort.

## Häufige Befehle

Alle Bench-Befehle laufen **im Backend-Container**:

```bash
# Migrate (nach DocType-Änderungen / neuen Patches)
docker exec hausverwaltung_peters-backend-1 bench --site frontend migrate

# Cache leeren (nach hooks.py-, fixture- oder Print-Format-Änderungen)
docker exec hausverwaltung_peters-backend-1 bench --site frontend clear-cache

# Asset-Build (JS/CSS in public/js/, public/css/) — braucht NVM-Sourcing,
# weil bench die Node-Version aus dem PATH zieht und im non-interactive Shell
# die nvm-Init nicht greift.
docker exec hausverwaltung_peters-backend-1 bash -lc \
  'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; \
   cd /home/frappe/frappe-bench && bench build --app hausverwaltung'

# Worker-Restart (für Python-Code-Änderungen, außer DocType-Schema)
docker restart hausverwaltung_peters-backend-1 \
               hausverwaltung_peters-queue-short-1 \
               hausverwaltung_peters-queue-long-1

# Tests (Python)
docker exec hausverwaltung_peters-backend-1 \
  bench --site frontend run-tests --app hausverwaltung
# Einzelner Test-Modul:
docker exec hausverwaltung_peters-backend-1 \
  bench --site frontend run-tests --module hausverwaltung.hausverwaltung.utils.test_mieter_name

# Cypress E2E (vom Host)
yarn cy:run     # headless
yarn cy:open    # interaktiv
```

Convenience-Skripte unter `apps/hausverwaltung_peters/`:

- `migrate.sh` — `docker compose restart` + `bench migrate`
- `bootstrap_site.sh` — Initial-Setup einer leeren Site (Sprache, Zeitzone, Company)
- `export_fixtures.sh` — Fixtures aus DB ins Repo exportieren
- `volume_snapshot.sh` — DB- & Files-Snapshot für lokale Backups

**Hooks-Cache-Falle:** `app_include_js` / `doctype_js`-Änderungen werden in einem Frappe-Cache gehalten. Nach Editieren der `hooks.py` immer **erst Worker neu starten, dann `clear-cache`**, sonst sieht der Browser die alten Asset-URLs.

## Architektur — das große Bild

### Domain-Modell

Zentrale DocTypes (in `hausverwaltung/doctype/`):

- **`Immobilie`** (Tree-DocType, `parent_immobilie` für Gebäudeteile VH/SF/HH)
- **`Wohnung`** — referenziert `Immobilie` und optional `immobilie_knoten` (Gebäudeteil)
- **`Mietvertrag`** — Wohnung × Vertragspartner mit `von` / `bis`. Customer-Name wird automatisch aus den **`Vertragspartner`-Childs mit `rolle="Hauptmieter"`** gesynced (siehe `utils/mieter_name.py`).
- **`Vertragspartner`** (Child) — Rolle: `Hauptmieter | Untermieter | Betreuer | Ausgezogen`
- **`Betriebskostenabrechnung Immobilie`** + Mieter-Childs — pro-Immobilie Verteilungsbasis (qm + Festbeträge), generiert Sales Invoices
- **`Serienbrief Vorlage`** — Brief-Templates mit Inline-Bausteinen (`{{ baustein("X") }}`) und Kategorie-Tree
- **`Serienbrief Durchlauf` → `Serienbrief Dokument`** — pro-Empfänger-Render-Pipeline mit gemerged-PDF-Output
- **`Einnahmen Ueberschuss Rechnung`** (EÜR) — Steuerreport mit Print Format

### Render-Pipeline für Briefe (sehr fragiler Teil)

Die Serienbrief-Render-Logik in `doctype/serienbrief_durchlauf/serienbrief_durchlauf.py` durchläuft drei Render-Pfade — wer hier ändert, muss beide kennen:

1. **`_create_dokumente`** rendert pro Empfänger HTML-Segmente und speichert **vorab** ein PDF in `Serienbrief Dokument.generated_pdf_file` (über `_render_segments_pdf_bytes` → unser `utils.pdf_engine.render_pdf` Wrapper).
2. **`_build_merged_pdf`** entscheidet beim PDF-Erzeugen pro Doc: `_render_dokument_with_print_format` (= `frappe.get_print(... as_pdf=True)`) ODER cached `generated_pdf_file` ODER direkter `get_pdf` Call.
3. **Inline-vs-Listen-Modus für Bausteine:** Wenn der Vorlagen-Content `{{ baustein("X") }}` enthält → Inline-Modus, alle Tabellen-Bausteine werden ignoriert. Sonst Listen-Modus, dann zählt `content_position` (`Vor Bausteinen` / `Nach Bausteinen`).

### Chrome-PDF-Engine + Frappe-Bug-Patch

Die Site nutzt **Chromium-Headless** als PDF-Engine (Print Settings → `pdf_generator = chrome`). `wkhtmltopdf` unterstützt kein CSS-Paged-Media (`position: fixed; bottom`, `@page` margins) und ist Frappe-seitig deprecated.

**Frappe v15 hat zwei Bugs in `frappe.utils.pdf_generator.browser.Browser.prepare_options_for_pdf`**, die `hausverwaltung/utils/frappe_chrome_footer_patch.py` workaround-fixt. Der Patch wird beim Modul-Import aus `hausverwaltung/__init__.py` idempotent appliziert und ist Voraussetzung dafür, dass Print Formats mit `<div id="footer-html">` (z.B. „Serienbrief Dokument" mit dynamischem Pfad-Footer) überhaupt rendern. Bug-Details stehen im Modul-Docstring.

Der Hausverwaltungs-Custom-PDF-Pfad ruft `frappe.utils.pdf.get_pdf` direkt auf, das hardcoded auf wkhtmltopdf ist — daher der `pdf_engine.render_pdf`-Wrapper, der je nach Setting Chrome oder wkhtmltopdf wählt. Im `serienbrief_durchlauf.py` wird der Wrapper als `get_pdf` re-importiert, damit existing Call-Sites weiterlaufen.

Beim Image-Build muss Chrome verfügbar sein. `apps/hausverwaltung_peters/docker/frappe-pdf2html.Dockerfile` installiert die nötigen GTK/Cups/NSS-Libraries; Chromium-Binary lädt Frappe selbst beim ersten Aufruf in `/home/frappe/frappe-bench/chromium/`.

### Hook-Topologie

`hooks.py` ist die zentrale Verdrahtung — wichtige Einträge:

- **`app_include_js`** (Liste) — globale Desk-JS-Helper. Neue Einträge werden vom Frappe-Cache gehalten; nach Änderung Worker-Restart + `clear-cache` nötig.
- **`doctype_js` / `doctype_list_js`** — Form-/List-Skripte für Stock-Frappe/ERPNext-DocTypes. Hausverwaltungs-eigene DocTypes haben ihr Skript direkt im DocType-Ordner (`<dt>.js`).
- **`doc_events`** — viele Auto-Sync-Hooks: Mietvertrag↔Wohnung-Status, Bank Account-Naming, Contact-Sync, Account→Kostenart, Communication→Paperless.
- **`after_migrate`** — lange Liste von `ensure_*`-Funktionen aus `install.py`, die idempotent Print Formats, Custom Fields, Property Setters und Workspace-Layouts setzen. Pattern: jede Funktion ist defensiv (skipt wenn Ziel schon korrekt ist).
- **`override_doctype_class`** — Custom Subklassen für `Payment Entry` und `Sales Invoice` in `overrides/`.
- **`scheduler_events.cron`** — nächtliche Mietvertrag-Status-Updates, Mahn-Kandidat-Refresh etc.

`__init__.py` lädt den Chrome-Footer-Patch beim ersten Import. Der Patch ist idempotent über ein `_PATCHED_FLAG`-Attribut auf der Browser-Klasse.

### Date-Range-Presets in Forms & Reports

`public/js/date_range_presets.js` exposed `window.hausverwaltung.date_presets` mit `attach_to_form(frm, opts)` (Form-Buttons unter Date-Feld) und `attach_to_query_report(report, opts)` (Inner-Button-Group in Query-Report-Toolbar). Beide Pfade sind in mehreren Forms/Reports eingehängt — siehe Aufrufer-Liste durch `grep "hausverwaltung.date_presets"`. Eingehängte Reports nutzen `frappe.require()` statt sich auf den `app_include_js`-Cache zu verlassen.

### Temporal Integration (optional)

Für `Mieterwechsel` und `Email Entwurf` ist Temporal optional aktivierbar. Steuerung über Site-Config-Keys (`hv_temporal_enabled`, `hv_temporal_enabled_doctypes`). Worker startet im Service `temporal-worker` via `bench execute hausverwaltung.hausverwaltung.integrations.temporal.worker.run`. Logik in `integrations/temporal/` (Activities, Adapters, Orchestrator). Wenn Flags aus sind, läuft alles synchron im normalen Frappe-Flow.

### Sprachnotizen

`page/sprachnotiz_aufnahme/` mit lokaler Transkription via `faster-whisper`. Optional Ollama für Anreicherung — wenn Endpoint nicht erreichbar, bleibt Doc auf `Teilweise verarbeitet` und Temporal versucht später erneut. Settings in `Hausverwaltung Einstellungen` (`ollama_enabled`, `ollama_base_url`, `ollama_model`, `whisper_model_size`).

### Paperless NGX Integration

`integrations/paperless.py` exportiert `Communication`-Records nach Paperless via `enqueue_paperless_export` (after_insert hook). Konfiguration über Site-Config (`paperless_ngx_url`, `paperless_ngx_token`, …). `retry_failed_exports` läuft stündlich.

### Konfigurations-Architektur

Zwei Quellen, je nach Phase:

- **Prozess-Environment** (Docker `environment:` / `env_file:`): nur beim **Bootstrap/Install** ausgewertet (`scripts/bootstrap_site.py`, `HV_*`-Variablen).
- **Site-Config** (`site_config.json`, gesetzt via `bench --site frontend set-config`): zur **Laufzeit** gelesen.

Wenn Du Runtime-Verhalten konfigurieren willst, ist es **immer** ein Site-Config-Key (in `set-config` setzbar), niemals `os.environ`-lesend.

## Linting / Code-Style

`pre-commit` ist konfiguriert (siehe README). Lokal:

```bash
cd apps/hausverwaltung
pre-commit install
pre-commit run --all-files
```

- **Python:** ruff (line-length **110**, target **py310**, `indent-style = "tab"`, `quote-style = "double"`)
- **JS:** eslint, prettier
- **Tabs, nicht Spaces** — auch in Python (siehe `pyproject.toml [tool.ruff.format]`)
