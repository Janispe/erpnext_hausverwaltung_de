# Serienbrief: DocType-Berechtigungsprüfung korrigieren

Stand: 2026-10-08. **Vorbereitet, nicht produktiv deployed.**

## Quellcode und wirksame Deployment-Struktur

Maßgeblich ist das Hausverwaltung-App-Repository mit
`hausverwaltung/hausverwaltung/agent_tools/{block_authoring_api,template_authoring_api}.py`.
Die drei administrativen `_read("DocType", ...)`-Aufrufe wurden durch den gemeinsamen
Helper `_require_doctype_read` ersetzt: interne Existenzprüfung via
`frappe.db.exists("DocType", name)`, anschließend das unveränderte
`frappe.has_permission(name, "read")`. Tatsächliche Dokumente verwenden weiterhin
`api._read` und `doc.check_permission`. Allowlisten und alle übrigen Prüfungen bleiben erhalten.

Der hier erreichbare Docker-Daemon betreibt `hvp-backend-1`, Site `frontend`, aus
`/home/janis/Documents/hausverwaltung/erp_next/production/frappe_docker/compose.custom.yaml`.
`/srv/hv/erpnext` existiert in dieser Sitzung nicht. Der getrennte Server ist damit
nicht verifiziert; diese lokalen Artefakte nicht ungeprüft auf einen anderen Host übertragen.

Backend, queue-short, queue-long und scheduler verwenden derzeit
`hvp:16-helpdesk-suite-fac`. Beide Module werden durch ältere Dateien aus
`runtime-overrides/serienbrief/hausverwaltung/...` überdeckt. Diese produktiven Dateien
und die aktive Compose-Datei wurden nicht geändert. Ein Image-Rebuild allein würde
die fehlerhaften Mount-Dateien weiter verwenden.

Der lokale Code verlangt für Vorschläge weiterhin `Hausverwalter` oder
`System Manager`; `MCP Serienbrief` allein ist hier nicht in der Rollenprüfung.
Der Fix verändert diese Schreibprüfung ausdrücklich nicht. Die erfolgreiche
Regression verwendet einen isolierten Testbenutzer mit der bereits vorausgesetzten
Rolle und ausschließlich Fachberechtigungen, ohne DocType-Leserecht. Es gab keine
produktiven Rechteänderungen. Der genaue Rollenstand des beschriebenen
`agent-readonly@example.com` auf `/srv/hv/erpnext` muss vor einem dortigen Deployment
lesend abgeglichen werden; eine abweichende Rollenprüfung ist kein Grund für zusätzliche Rechte.

## Validierung

Isolierte Site `fac.localhost`, eigener Stack `hv-fac-test`, eigene DB-/Site-/Log-Volumes.
Kein produktives Netzwerk und keine produktiven Volumes in den Testcontainern.

- 8 neue Integrationstests: Referenzvariable `Immobilie` und Standardpfade ohne
  DocType-Leserecht, unveränderter aktiver Bank-Testbaustein, fehlende Fachrechte,
  unzulässige Datentypen/Pfade, nicht vorhandene Typen und Vorlagenempfängertypen.
- 12 bestehende Bausteintests und 27 bestehende Vorlagentests bestanden.
- Die neuen Tests bestehen auch mit den minimal gepatchten älteren Produktionsmodulen.
- Gegenprobe mit unveränderten Produktionsmodulen: positive Vorschlags- und
  Vorlagentests scheitern mit `PERMISSION_DENIED`; insgesamt 7 erwartete Assertions
  in 4 Testmethoden fehlgeschlagen, einschließlich Subtests, die der Fehler vorzeitig abweist.
- Ruff-Prüfung, Formatprüfung und `git diff --check` bestanden.

Testberechtigungen werden pro Test durch Savepoint-Rollback entfernt; keine
Installationshooks oder Rollenfixtures wurden geändert. PDFs und Entwürfe wurden
nur von vorhandenen Tests innerhalb der isolierten Testsite erzeugt.

Zum Wiederholen auf einer vorhandenen, entsprechend vorbereiteten Testsite:

```bash
docker exec hv-fac-test-backend-1 bench --site fac.localhost run-tests \
  --module hausverwaltung.hausverwaltung.agent_tools.test_authoring_doctype_permissions
docker exec hv-fac-test-backend-1 bench --site fac.localhost run-tests \
  --module hausverwaltung.hausverwaltung.agent_tools.test_block_authoring
docker exec hv-fac-test-backend-1 bench --site fac.localhost run-tests \
  --module hausverwaltung.hausverwaltung.agent_tools.test_template_authoring
```

## Minimaler Kandidat

`scripts/prepare_authoring_permission_image.py` liest die effektiven zwei Module
aus dem Backend, wendet den versionierten Patch ohne Fuzz an und baut ein neues
Image auf der tatsächlich laufenden Image-ID. Es startet keine Container und führt
keine Site-Befehle aus. Neue Tags dürfen bestehende oder aktive Tags nicht überschreiben.
Andere App-Versionen, FAC-Konfigurationen und Rollenprüfungen bleiben erhalten.

Bereits erzeugt:

- Image: `hvp:authoring-permissions-20261008-reviewed`
- Image-ID: `sha256:b009fe89687ea40bd277195005b358d7707ade678c3c2298d182754ff43690aa`
- Staging: `/tmp/hv-authoring-permissions-20261008-reviewed`
- Darin: Dockerfile, gepatchte Module, Hash-Manifest, Compose-Override.

Auf einem anderen Host aus dessen effektivem Stand **neu** vorbereiten und isoliert testen:

```bash
python3 scripts/prepare_authoring_permission_image.py \
  --project hvp --image hvp:authoring-permissions-NEUER-EINDEUTIGER-TAG \
  --output /tmp/hv-authoring-permissions-NEUER-EINDEUTIGER-TAG
```

## Deployment erst nach ausdrücklicher Freigabe

Die folgenden Schritte wurden **nicht ausgeführt**. Sie gelten für den hier
verifizierten lokalen Stack. Falls sich dessen Dateien, Mounts oder Images seit
der Vorbereitung geändert haben, zuerst einen neuen Kandidaten erstellen und testen.

Nach Freigabe die Artefakte dauerhaft ablegen, Images/Mounts für Rollback erfassen
und ein Site-Backup erstellen:

```bash
cd /home/janis/Documents/hausverwaltung/erp_next/production/frappe_docker
mkdir -p deployment-candidates
cp -a /tmp/hv-authoring-permissions-20261008-reviewed deployment-candidates/
python3 scripts/snapshot_runtime.py --project hvp
docker exec hvp-backend-1 bench --site frontend backup --with-files
```

Der konkrete Umschaltschritt:

```bash
docker compose -p hvp -f compose.custom.yaml \
  -f deployment-candidates/hv-authoring-permissions-20261008-reviewed/compose.authoring-permissions.yaml \
  up -d --no-deps --force-recreate backend queue-short queue-long scheduler
```

Dieser reine Python-Fix benötigt keine Datenbankmigration, keine Asset-Builds und
keine FAC-Neukonfiguration. Keine `enable_external_tools`-Aufrufe und keine
Rechtevergabe. Danach Image-ID und fehlende Modulmounts lesend prüfen. Kein
produktiver Vorschlag, PDF oder Mailentwurf als Smoke-Test ohne gesonderten Auftrag.

Rollback: den von `snapshot_runtime.py` ausgegebenen Override zusammen mit dem
bisherigen Basis-Compose verwenden und dieselben vier Dienste neu erstellen.
Da keine Schemaänderung vorgenommen wird, ist hierfür kein DB-Restore erforderlich.

## Dauerhaftigkeit bei Neuerstellung und Updates

Der Fix liegt im versionierten App-Quellcode. Änderungen, Tests, Vorbereitungsskript
und Patch müssen vor dem regulären Git-basierten Image-Build gemeinsam in den
Deployment-Branch übernommen werden. Ein Push und die Übernahme auf den
Deployment-Host sind separate Schritte.

Bis zur Übernahme in das reguläre Image ist der oben abgelegte Override bei jedem
Compose-Aufruf zu verwenden. Für spätere reguläre Updates müssen die acht
Bind-Mount-Einträge für genau diese zwei Module (je vier Python-Dienste) auch aus
der maßgeblichen Basis-Compose-Konfiguration entfernt werden. Andere Overrides
bleiben erhalten. Danach das reguläre Image aus dem Branch mit dem Quellcode-Fix
bauen und isoliert prüfen; erst dann den Kandidaten-Override aus dem Updateweg lösen.

Ein alleiniger `update.sh`-Aufruf würde aktuell die alten Modulmounts beibehalten;
er enthält außerdem Migration und FAC-Neukonfiguration und ist deshalb kein
passender minimaler Deployment-Schritt für diesen Fix.
