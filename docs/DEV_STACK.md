# Entwicklungsumgebung (ohne `hausverwaltung_peters`)

Zwei Wege, beide ohne die private Companion-App: es gibt keinen Mount, keine
Installation und kein gemeinsames Volume, über das Mandantendaten in diese
Sites gelangen könnten.

| | Devcontainer | Compose-Stack |
|---|---|---|
| Datei | `.devcontainer/` | `compose.dev.yml` |
| Voraussetzung | **nur dieses Repo** + Docker | dieses Repo **und** drei Nachbar-Clones |
| übrige Apps | klont der Container selbst | als Geschwisterordner gemountet |
| Docker | eigener Daemon im Container | Daemon des Hosts |
| Host-Pfade sichtbar | keine | die drei App-Ordner |
| Webserver | nginx, Port 8180 (weitergereicht) | nginx, Port 8180 |

**Devcontainer**, wenn die Umgebung abgeschottet sein soll — etwa weil ein
Coding-Assistent darin arbeitet, der nichts Privates sehen darf. Der Stack
läuft dann auf einem eigenen Docker-Daemon im Container.

**Compose-Stack**, wenn du parallel an mehreren der Apps entwickelst oder
etwas testest, das dauerhaft laufende Worker, den Scheduler oder den nginx
braucht (Hintergrund-Jobs, Cron, Serienbrief-Durchläufe).

Beide Projekte haben eigene Volumes und stören sich gegenseitig nicht.

---

# Devcontainer (isoliert)

Gedacht für den Fall, dass in der Umgebung ein Coding-Assistent arbeitet, der
nichts Nichtöffentliches sehen darf. Der Container bekommt deshalb **keinen
einzigen Host-Pfad** durchgereicht und kennt nur öffentliche Repos.

Installiert werden **alle Apps des Projekts ausser der privaten
`hausverwaltung_peters`**:

| App | Repo | |
|---|---|---|
| `hausverwaltung` | `Janispe/erpnext_hausverwaltung_de` | öffentlich |
| `process_engine` | `Janispe/process_engine` | öffentlich |
| `mail_merge` | `Janispe/erp_next_mail_merge` | öffentlich |
| `thunderbird_hausverwaltung` | `Janispe/thunderbird_hausverwaltung_erpnext` | öffentlich |

```bash
git clone https://github.com/Janispe/erpnext_hausverwaltung_de.git hausverwaltung
code hausverwaltung
# VS Code: "Reopen in Container"
```

`postCreateCommand` klont die übrigen drei als Geschwisterordner daneben —
anonym über HTTPS, also ohne Credentials im Container. Danach im Container-Terminal:

```bash
./dev.sh up
```

Das startet `compose.dev.yml` auf dem **inneren** Docker-Daemon. Erster Lauf
10–20 Minuten, danach **http://localhost:8180** (VS Code reicht den Port
weiter), `Administrator` / `admin`.

Alle `dev.sh`-Befehle gelten drin genauso: `restart`, `migrate`, `cache`,
`build`, `test`, `nuke`.

## Wie die Isolation hält

| | |
|---|---|
| **Kein `mounts`-Eintrag** | Weder `~/.ssh` noch `~/.gitconfig` noch ein Nachbar-Repo erreichen den Container. Er sieht dieses Repo und was er sich selbst holt. |
| **Docker-in-Docker statt `docker.sock`** | Der Host-Socket wäre ein vollständiger Ausbruch: wer ihn hat, startet einen Container mit `-v /:/host` und liest jede Datei des Hosts. Hier läuft ein eigener Daemon im Container, die Bind-Mounts der inneren compose zeigen deshalb in dessen Dateisystem. |
| **Nur öffentliche Repos** | Alle drei anonym klonbar. Es liegen keine Zugangsdaten im Container, also kann von dort auch nichts gepusht werden. |

Das private `Janispe/hausverwaltung` und `hausverwaltung_peters` sind nicht
beteiligt — weder als Mount noch als Clone-Ziel.

Zwei Dinge, die das **nicht** abdeckt: der Container hat normalen
Netzwerkzugang, und `--privileged` (vom docker-in-docker-Feature gesetzt)
schwächt die Container-Grenze gegenüber dem Kernel. Gegen einen
vertrauenswürdigen, aber neugierigen Assistenten reicht das; gegen einen
aktiven Angreifer auf dem Host wäre eine VM die richtige Grenze.

---

# Compose-Stack

Vollständiger Stack mit nginx, Workern und Scheduler. Teilt weder Volumes
noch Netzwerke mit dem Produktivsystem.

## Umfang

`compose.dev.yml` installiert **alle Apps des Projekts ausser der privaten
`hausverwaltung_peters`**: `process_engine`, `mail_merge`, `hausverwaltung`
und `thunderbird_hausverwaltung`, in dieser Reihenfolge.

Gesteuert wird das über `HV_APPS`. Einträge, deren Ordner nicht ausgecheckt
ist, überspringt der Start mit einer Meldung — ein Clone nur dieses Repos ist
also ebenfalls lauffähig, ihm fehlen dann eben die übrigen Apps.

`hausverwaltung_peters` ist bewusst nicht vorgesehen: nicht in `HV_APPS`,
nicht als Mount.

## Voraussetzung: Ordnerlayout

Die Repos müssen als Geschwister liegen, Ordnername = `app_name`:

```
apps/
  hausverwaltung/              <- hier liegt diese Datei
  process_engine/
  mail_merge/
  thunderbird_hausverwaltung/
```

```bash
mkdir -p ~/dev/hv/apps && cd ~/dev/hv/apps
git clone https://github.com/Janispe/erpnext_hausverwaltung_de.git hausverwaltung
git clone --branch master https://github.com/Janispe/process_engine.git
git clone --branch main   https://github.com/Janispe/erp_next_mail_merge.git mail_merge
git clone https://github.com/Janispe/thunderbird_hausverwaltung_erpnext.git thunderbird_hausverwaltung
```

Achtung beim dritten Clone: das Repo heißt `erp_next_mail_merge`, der Ordner
muss `mail_merge` heißen.


## Start

```bash
cd ~/dev/hv/apps/hausverwaltung
./dev.sh up
```

Erster Lauf baut das Image (Chromium-Bibliotheken) und legt die Site an —
je nach Maschine 10–20 Minuten. Danach:

- **http://localhost:8180** — `Administrator` / `admin`
- MariaDB auf `127.0.0.1:3307`

Beide Ports hängen an `127.0.0.1`, sind also nicht über LAN oder Tailscale
erreichbar.

## Täglich

```bash
./dev.sh restart          # nach Python-Änderungen
./dev.sh migrate          # nach DocType-Änderungen / neuen Patches
./dev.sh cache            # nach hooks.py-, Fixture-, Print-Format-Änderungen
./dev.sh build            # nach JS/CSS in public/
./dev.sh test             # bench run-tests --app hausverwaltung
./dev.sh nuke && ./dev.sh up   # Site komplett neu aufsetzen
```

Die App-Repos sind als Volume gemountet — Code-Änderungen wirken nach
`restart` sofort, ohne Rebuild.

## Wie die Trennung durchgesetzt wird

| Mechanismus | Wirkung |
|---|---|
| `name: hv-dev` in der compose | Volumes heißen `hv-dev_*`, können die Produktiv-Volumes nicht treffen — auch ohne `-p` |
| kein `shared_net` | keine Netzwerkverbindung zu Paperless oder zum Produktiv-Stack |
| kein `hausverwaltung_peters`-Mount | Importer, Cleanup-Helper und `import/` sind nicht erreichbar |
| Ports 8180 / 3307 auf `127.0.0.1` | keine Kollision mit 8080 / 3306, keine Erreichbarkeit von außen |
| eigene Company `Demo Hausverwaltung` | keine Verwechslung mit Produktivdaten im UI |

Nach Änderungen an der compose lohnt der Gegencheck:

```bash
docker compose -f compose.dev.yml config | grep -in 'peters\|shared_net\|paperless'
```

Muss leer bleiben. `config` löst Anchors, Defaults und relative Pfade auf,
zeigt also was Docker wirklich mountet.

## Unterschiede zum Produktivsystem

Bewusst nicht enthalten: Caddy/TLS, Temporal (4 Services), Paperless-NGX-
Anbindung. Wer daran entwickelt, hängt sie als Overlay-compose dazu.

Anders gesetzt ist außerdem `HV_BOOTSTRAP_CREATE_COA=1`: die Dev-Site legt
den SKR03-Kontenrahmen selbst an. Produktiv kommt er über den Import.

## Offener Punkt: leere Site

`hausverwaltung_peters` hängt fünf Setups in `after_migrate`, die hier
fehlen — Brand-Assets, die BK-Serienbrief-Vorlage, die Pfad- und
Bankverbindungs-Bausteine sowie `ensure_chrome_pdf_generator`.

`pdf_generator = chrome` setzt die compose beim Anlegen der Site selbst, der
PDF-Pfad entspricht also dem produktiven. Es fehlen aber sämtliche
Serienbrief-Vorlagen und alle Stammdaten. Für Betriebskosten-, Mahn- und
Serienbrief-Arbeit braucht es ein Seed-Skript mit synthetischen Immobilien,
Wohnungen und Mietverträgen unter `scripts/` — das gibt es noch nicht.
