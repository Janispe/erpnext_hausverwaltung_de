### Hausverwaltung

Frappe-App für die Hausverwaltung: Mietverträge, Betriebskosten-Abrechnung, Bankabgleich, Mahnwesen, Serienbriefe.

### Dokumentnummern und Production-Migration

Neue fachliche Dokumente erhalten eine kurze, unveränderliche Nummer. Der separat
gespeicherte Titel enthält Namen, Adresse, Lage oder Zeitraum und wird in Listen
und Link-Auswahlen angezeigt. `customer_name` bleibt der Personen-/Firmenname für
Belege; `Customer.hv_display_title` zeigt den Vertragskontext. Jeder Mietvertrag
erhält weiterhin einen eigenen Customer, auch bei derselben Person oder Wohnung.

| Dokument | Neue Nummer |
|---|---|
| Immobilie / Wohnung / Mietvertrag / Debitor | `IMM-00001` / `WHG-00001` / `MV-00001` / `DEB-00001` |
| Zähler / Zählerzuordnung / Wohnungszustand | `ZAE-00001` / `ZAZ-00001` / `WZS-00001` |
| Bankauszug / Kreditvertrag / Vertragsbuilder | `BAI-00001` / `KV-00001` / `MVB-00001` |
| BK-Abrechnung Immobilie / Mieter | `BKAI-2026-00001` / `BKAM-2026-00001` |
| HK-Abrechnung Immobilie / Mieter | `HKAI-2026-00001` / `HKAM-2026-00001` |
| Problem / EÜR / alte BK-Rechnung | `PROB-2026-00001` / `EUER-2026-00001` / `BKR-00001` |

Jahresserien beziehen sich auf das Kalenderjahr der Anlage, nicht auf den
Abrechnungszeitraum. Nummern werden über Frappes transaktional gesperrten
Serienzähler vergeben; auch die erste gleichzeitige Verwendung eines neuen
Jahrespräfixes wird serialisiert. Amendments behalten Frappes Suffix-Regel.
Vorhandene kurze Serien für Wartung, Anlagen und Prozesse sowie die
ERPNext-Belegnummern bleiben bestehen. Fachliche Codes von Regeltypen/Vorlagen
und technische Hashes für Mail-Synchronisation behalten ihren Zweck.

Die Migration `migrate_document_naming` benennt **keinen Bestandsdatensatz um**.
Sie ergänzt Titel und Metadaten und erhöht Serienzähler bei Bedarf auf bereits
vorhandene Nummern. Wiederholte Ausführung senkt keine Zähler und lässt IDs,
`creation`, `modified`, Buchungsreferenzen sowie die Vertragszuordnung bestehen.
Es werden keine fachlichen Dokumente gespeichert oder gebucht und keine
Archiv-/Mail-Synchronisationshooks ausgelöst. Eingebettete Abrechnungskennungen,
QR-Links und externe Mail-Tags bleiben dadurch gültig.

Der reguläre Updatepfad baut Images aus veröffentlichten Repository-Ständen.
Zum Release gehören die Änderungen in **hausverwaltung, hausverwaltung_peters,
process_engine und mail_merge**. Lokale Arbeitskopien gelangen nicht automatisch
in das Produktionsimage. Build, Snapshot, Sicherung und Rollback sind in der
Production-Datei `docs/hausverwaltung-deployment.md` beschrieben.

Für ein Upgrade:

1. Kandidatenimage bauen und auf einer getrennten Datenbankkopie prüfen. Ein
   anderer Compose-Projektname allein isoliert die vorhandene Production-Compose
   nicht: deren Sites-/DB-/Redis-Volumes und Netzwerk haben feste Namen. Für den
   Test eigene Volumes und ein eigenes Netzwerk ohne Worker/Scheduler verwenden.
2. Den Kandidaten-Vorabcheck auf der Kopie ausführen. Aktive abweichende
   `Document Naming Rule`/Namens-Overrides, fehlende Vertragslinks und mehrfach
   verwendete Customers müssen vor dem Upgrade bereinigt werden. Der Check
   errät keine Zuordnung und schreibt keine Geschäftsdaten:

   ```sh
   bench --site <site> execute hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_document_naming.preflight
   ```

   Für den zusätzlichen Vergleich von Zeitstempeln und Buchungs-/Mailreferenzen
   den Kandidatencode auf derselben Kopie vor und nach `migrate` aufrufen und die
   Ergebnisse vergleichen:

   ```sh
   bench --site <site> execute hausverwaltung.hausverwaltung.utils.document_naming_audit.reference_snapshot
   ```

   Das Ergebnis enthält ausschließlich Anzahlen und Prüfsummen. Diese optionale
   Prüfung liest auch die Hauptbuchtabelle und benötigt entsprechend Speicher.

3. Im Wartungsfenster Worker/Scheduler anhalten, ein vollständiges
   `bench --site <site> backup --with-files` samt Site-Konfiguration und altem
   Image sichern, dann das Kandidatenimage über den regulären Updatepfad
   installieren und `bench --site <site> migrate` ausführen. Bei einem
   Migrationsfehler abbrechen; diese Migration nicht mit `--skip-failing` umgehen.
4. Den Vorabcheck erneut ausführen. `document_ids_sha256` und
   `contract_links_sha256` müssen während desselben schreibfreien Wartungsfensters
   vor/nach dem Upgrade übereinstimmen. Die Titelanzeige eines alten Vertrags und
   die Anlage eines neuen Vertrags einschließlich eigenem `DEB-…` kontrollieren.
   Danach Worker/Scheduler wieder starten.

Ein reiner Image-Rollback stellt die Datenbank nicht zurück. Falls eine
Datenbankwiederherstellung nötig ist, die zugehörige Sicherung und
Site-Konfiguration verwenden; neuere Buchungen müssen dabei berücksichtigt
werden. Bestehende IDs werden auch im Fehlerfall nicht durch eine allgemeine
Umbenennung oder Customer-Zusammenführung ersetzt.

Die Umstellung wurde am 7. Oktober 2026 auf einer isolierten Kopie des
Produktionsbestands mit 364 Mietverträgen geprüft. Der Vergleich von 33 Tabellen
einschließlich 241.766 Hauptbuchzeilen ergab unveränderte Identitäten,
Zeitstempel und Referenzen. Zweimaliges erneutes Backfill lieferte identische
Titel; zwei parallele Erstanlagen eines neuen Jahrespräfixes erhielten getrennte
Nummern. Die Produktionsdatenbank wurde für diesen Test nicht migriert.
Zusätzlich bestanden 217 gezielte Tests, einschließlich wiederholter CSV- und
Sample-Importe mit kurzen IDs und der Abweisung mehrdeutiger Zuordnungen.

### Automatische Mietsollstellung

Unter **Hausverwaltung Einstellungen → Mietsollstellung → Mieten automatisch monatlich
sollstellen** lässt sich der monatliche Rechnungslauf einschalten (standardmäßig aus).
Der erste automatische Lauf erfolgt zum nächsten Monatsanfang. Er erstellt und bucht
für alle Firmen die Miete, Betriebs- und Heizkostenvorauszahlungen sowie
Untermietzuschläge gemäß Mietvertrag. Vorhandene Rechnungen einschließlich Entwürfen
werden durch die bestehende Dublettenprüfung berücksichtigt.

Die Ergebnisse stehen unter **Mietrechnungen Durchlauf**, Fehler unter **Error Log / Failed Jobs**.
Scheduler und Worker für die Queue `long` müssen laufen. Nach dem Einspielen der
Änderung registriert `bench --site <site> migrate` die Einstellung und den monatlichen
Scheduler-Job. Bei einer Scheduler-Unterbrechung wird der fällige Lauf nach dem
Wiederanlauf für den dann aktuellen Monat ausgeführt; frühere Monate werden nicht nachgeholt.

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
