### Hausverwaltung

Frappe-App für die Hausverwaltung: Mietverträge, Betriebskosten-Abrechnung, Bankabgleich, Mahnwesen, Serienbriefe.

### Temporal (Kern-Workflows)

Temporal ist fuer `Mieterwechsel` und `Email Entwurf` integriert und per Feature-Flags steuerbar.

- Compose Services: `temporal-postgresql`, `temporal`, `temporal-ui`, `temporal-worker`
- Temporal UI: `http://localhost:8081`
- Worker Start erfolgt im Service `temporal-worker` via `bench --site frontend execute hausverwaltung.hausverwaltung.integrations.temporal.worker.run`

#### Site-Config Keys

- `hv_temporal_enabled`
- `hv_temporal_enabled_doctypes`
- `hv_temporal_address` (default `temporal:7233`)
- `hv_temporal_namespace` (default `hausverwaltung`)
- `hv_temporal_task_queue_process` (default `hv-process`)
- `hv_temporal_task_queue_email` (default `hv-email`)
- `hv_temporal_ui_url` (default `http://temporal-ui:8080`)

Beispiel (Site `frontend`):

```bash
bench --site frontend set-config hv_temporal_enabled true
bench --site frontend set-config hv_temporal_enabled_doctypes "Mieterwechsel,Email Entwurf,Sprachnotiz"
```

### Sprachnotizen

- Neue Seite: `sprachnotiz-aufnahme`
- Lokale Transkription erfolgt ueber `faster-whisper` im ERPNext/Worker-Umfeld.
- Ollama ist optional und darf remote auf einem anderen Rechner laufen, z.B. deinem PC im Heimnetz.
- Wenn der konfigurierte Ollama-Endpunkt nicht erreichbar ist, bleibt die Sprachnotiz auf `Teilweise verarbeitet` und Temporal versucht die Anreicherung spaeter erneut.
- Relevante Felder in `Hausverwaltung Einstellungen`:
  - `ollama_enabled`
  - `ollama_base_url`
  - `ollama_model`
  - `ollama_timeout_seconds`
  - `default_transcript_language`
  - `whisper_model_size`

Empfohlener Rollout:

1. Deploy + migrate bei deaktivierten Flags.
2. Temporal Services starten.
3. Flags schrittweise aktivieren.
4. Monitoring in App-Logs + Temporal UI.

### Konfiguration

Die App liest ihre Konfiguration aus zwei Quellen — abhängig davon, wann sie gebraucht wird:

- **Prozess-Environment** (Docker `environment:` / `env_file:`, oder Shell-Export vor `bench`-Start) — nur beim **Installer/Bootstrap** ausgewertet.
- **Site-Config** (`site_config.json`, gesetzt via `bench --site <site> set-config <key> <value>`) — zur **Laufzeit** gelesen.

#### Bootstrap (Prozess-Environment, optional)

Steuern das Verhalten des initialen Site-Setups via `scripts/bootstrap_site.py`. Werden nur beim ersten Install ausgewertet.

| Variable | Default | Zweck |
|---|---|---|
| `HV_LANGUAGE` | `de` | Sprache der initialen Site (`de` / `en`) |
| `HV_COMPANY` | — | Firmenname für die Default-Company |
| `HV_COUNTRY` | `Germany` | Land |
| `HV_TIME_ZONE` | `Europe/Berlin` | Zeitzone |
| `HV_CURRENCY` | `EUR` | Währung |
| `HV_COA_TEMPLATE` | `SKR03 mit Kontonummern` | Kontenrahmen |
| `HV_BOOTSTRAP_RUN_SETUP_WIZARD` | `0` | Setup-Wizard automatisch ausführen |
| `HV_BOOTSTRAP_MARK_SETUP_COMPLETE` | `1` | Setup nach Bootstrap als abgeschlossen markieren |
| `HV_BOOTSTRAP_CREATE_COA` | `0` | Kontenrahmen automatisch anlegen |

#### Paperless NGX (Site-Config)

Werden zur Laufzeit gelesen ([`integrations/paperless.py`](hausverwaltung/integrations/paperless.py)).

```bash
bench --site <site> set-config paperless_ngx_url "https://paperless.example.com"
bench --site <site> set-config paperless_ngx_token "<dein-token>"
bench --site <site> set-config paperless_ngx_public_url "https://paperless.example.com"
```

Optional: `paperless_ngx_correspondent_id`, `paperless_ngx_document_type_id`, `paperless_ngx_tag_ids` (Liste), `paperless_ngx_tag_email_id`, `paperless_ngx_tag_attachment_id`, `paperless_ngx_custom_field_link_id`, `paperless_ngx_timeout` (Default `20`), `paperless_ngx_verify_ssl` (Default `true`).

### Sample-Daten

```bash
bench --site <site> execute hausverwaltung.hausverwaltung.data_import.sample.run_all \
  --kwargs '{"company": "Your Company"}'
```

`company` ist Pflicht — es gibt keinen impliziten Default.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app hausverwaltung
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/hausverwaltung
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
