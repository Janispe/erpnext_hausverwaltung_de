# Übergabe: Thunderbird-Archiv nach lokalem Stalwart testen

## Auftrag

Führe auf dem Laptop `janis-HP-Pavilion-x360-Convertible-14-dh1xxx` einen
vollständigen, kontrollierten Testimport der vorbereiteten privaten lokalen
Thunderbird-Ordner in das lokale Stalwart-Entwicklungskonto
`archiv@archiv.test` aus.

Quelle auf diesem Laptop:

```text
/media/janis/MemoryBoard/email sicherung 19_08_2026/test_stalwart_migration/privat
```

Stalwart läuft ebenfalls auf diesem Laptop. Ermittle dessen tatsächliche lokale
JMAP-URL aus der laufenden Konfiguration bzw. dem Container; keine Portnummer
raten.

Die gewünschte Kette ist:

```text
Thunderbird mbox + .sbd
  -> bereitgestellter Konverter
  -> temporäres Dovecot/Maildir (nur 127.0.0.1)
  -> Vandelay-SQLite-Archiv
  -> lokales Stalwart-Konto archiv@archiv.test
```

## Unverhandelbare Sicherheitsregeln

- Die Thunderbird-Quelle ausschließlich lesend verwenden. Nichts darin
  verschieben, löschen, komprimieren oder umbenennen.
- Für jeden Versuch ein neues, leeres, zeitgestempeltes Arbeitsverzeichnis
  anlegen. Vorhandene Ziele nicht überschreiben.
- Kein Vandelay `--prune` verwenden.
- Vor dem Export nach Stalwart nach der Konvertierung und der
  Vandelay-Inspektion anhalten und die Ergebnisse prüfen.
- Bei Konverter-Warnungen, `partial_messages > 0` oder
  `keyword_overflow > 0` nicht weiterimportieren, sondern den Befund melden.
  `expunged_skipped > 0` ist erwartbar und bedeutet, dass in Thunderbird als
  gelöscht markierte, aber noch physisch in der mbox vorhandene Nachrichten
  bewusst ausgelassen wurden.
- Passwörter nicht in Chat, Dateien oder Kommandoargumente schreiben. Für
  Stalwart verdeckt einlesen und über die von Vandelay unterstützte
  Umgebungsvariable bereitstellen. Das Dovecot-Kennwort ist nur ein temporäres
  Testkennwort für einen localhost-only Container.
- Thunderbird-Kopie, Arbeitsverzeichnis, Konvertierungsbericht und
  Vandelay-SQLite-Datei bis nach der fachlichen Kontrolle aufbewahren.
- Falls installierte Versionen eine andere CLI-Syntax verlangen, zuerst
  `--help` und die offizielle Dokumentation prüfen; keine potenziell
  verändernde Option erraten.

## Bereits vorbereitete und geprüfte Dateien

- `thunderbird_mbox_to_dovecot.py`: liest Thunderbird-mbox-Dateien mit
  gleichnamigen `.sbd`-Unterordnern und erzeugt Dovecot Maildir mit
  `LAYOUT=fs`.
- `test_thunderbird_mbox_to_dovecot.py`: Tests für Hierarchie, Punkte in
  Ordnernamen, Flags, Tags, expunged-Nachrichten und mbox-Unescaping.
- `dovecot/99-thunderbird-migration.conf`: temporärer IMAP-Dienst als Benutzer
  `migration`, gebunden an Port 31143.

Der Konverter:

- öffnet die Quelle read-only;
- ignoriert `.msf`-Indexdateien;
- erhält `.sbd`-Hierarchien und Punkte in Ordnernamen;
- übersetzt gelesen/beantwortet/markiert/weitergeleitet sowie Thunderbird-Tags;
- überspringt als `Expunged` markierte Nachrichten;
- erkennt partielle Nachrichten;
- schreibt atomar und verweigert ein nichtleeres Ziel;
- legt alles unter dem IMAP-Ordner `Thunderbird-Archiv` ab;
- schreibt `Maildir-conversion-report.json` neben das Maildir.

## Vorgehen

### 1. Voraussetzungen und Quelle nur lesend prüfen

Arbeite aus dem Verzeichnis, in dem dieses Dokument unter
`scripts/mail_migration/HANDOFF.md` liegt. Prüfe Hostname, Mount, verfügbaren
Speicher, Docker sowie die vorhandenen Dateien. Inventarisiere die Quelle
read-only. Führe anschließend die Tests aus:

```bash
python3 -m unittest discover \
  -s scripts/mail_migration \
  -p 'test_*.py'
```

### 2. In ein neues Staging-Maildir konvertieren

Lege ein neues Arbeitsverzeichnis an, zum Beispiel unter einem ausreichend
großen Datenträger. Verwende keine bereits gefüllte Zielstruktur:

```bash
SOURCE='/media/janis/MemoryBoard/email sicherung 19_08_2026/test_stalwart_migration/privat'
TOOLS="$PWD/scripts/mail_migration"
WORK="/tmp/thunderbird-stalwart-test-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$WORK/vmail/migration"

python3 "$TOOLS/thunderbird_mbox_to_dovecot.py" \
  "$SOURCE" \
  "$WORK/vmail/migration/Maildir"
```

Prüfe danach den kompletten Bericht:

```bash
python3 -m json.tool "$WORK/vmail/migration/Maildir-conversion-report.json"
```

Nur fortfahren, wenn `warnings` leer, `partial_messages` gleich 0 und
`keyword_overflow` gleich 0 ist. Notiere insbesondere die Gesamtzahl
`messages`; sie muss später mit Vandelay verglichen werden.

### 3. Temporäres, nur lokal erreichbares Dovecot starten

Die bereits gegen das offizielle Dovecot-Image geprüfte Konfiguration erwartet
den Benutzer `migration`. Vor dem Start sicherstellen, dass Port 31143 nicht
belegt ist.

```bash
CONTAINER='thunderbird-migration-dovecot'

docker run --detach --rm \
  --name "$CONTAINER" \
  --cap-add SYS_CHROOT \
  --security-opt no-new-privileges \
  --publish 127.0.0.1:31143:31143 \
  --env USER_PASSWORD='migration-test-only' \
  --volume "$WORK/vmail:/srv/vmail" \
  --volume "$TOOLS/dovecot/99-thunderbird-migration.conf:/etc/dovecot/conf.d/99-thunderbird-migration.conf:ro" \
  dovecot/dovecot:2.4.3-dev
```

Kontrolliere Dienst und Ordnerbaum:

```bash
docker logs "$CONTAINER"
docker exec "$CONTAINER" doveadm mailbox list -u migration
```

### 4. Mit Vandelay zunächst in SQLite importieren

Installiere Vandelay nur dann nach der offiziellen Stalwart-Anleitung, wenn es
noch nicht vorhanden ist. Verwende eine neue Archivdatei:

```bash
ARCHIVE="$WORK/private-vandelay.sqlite3"
export VANDELAY_PASSWORD='migration-test-only'

vandelay import imap --dry-run \
  --url imap://127.0.0.1:31143 \
  --auth-basic migration \
  --allow-cleartext \
  --noautomap \
  "$ARCHIVE"
```

Wenn die Vorschau stimmt, denselben Befehl ohne `--dry-run` ausführen. Danach
das Archiv mit den vorhandenen Vandelay-`inspect`-Unterbefehlen untersuchen
(`vandelay inspect --help` zuerst ansehen). Prüfe:

- Ordnerbaum einschließlich tiefer Unterordner und Punkte in Namen;
- Gesamtzahl der E-Mails gegen `messages` im Konvertierungsbericht;
- Stichproben aus alten und neuen Jahren;
- gelesen/beantwortet/markiert/weitergeleitet und Tags;
- mehrere Nachrichten mit Anhängen sowie deren Größe/Öffnbarkeit.

Bei Abweichungen hier stoppen. Wenn alles stimmt, den temporären Dovecot-Dienst
beenden; wegen `--rm` wird nur der Container entfernt, nicht `$WORK`:

```bash
docker stop "$CONTAINER"
```

### 5. Kontrolliert nach lokalem Stalwart exportieren

Ermittle zuerst die tatsächliche lokale JMAP-URL des laufenden Stalwart und
prüfe die von der installierten Vandelay-Version angebotene Syntax mit
`vandelay export --help`. Lies das Stalwart-Passwort verdeckt ein:

```bash
read -rsp 'Stalwart-Passwort: ' VANDELAY_PASSWORD
echo
export VANDELAY_PASSWORD
```

Dann zuerst die Vorschau ausführen. `$STALWART_URL` muss vorher auf die
ermittelte lokale JMAP-Basis-URL gesetzt worden sein:

```bash
vandelay export --dry-run \
  --url "$STALWART_URL" \
  --auth-basic 'archiv@archiv.test' \
  --account-name 'archiv@archiv.test' \
  --objects mailbox,email \
  "$ARCHIVE"
```

Kein `--prune`. Wenn Zielkonto, Anzahl und Ordner korrekt angezeigt werden,
denselben Befehl ohne `--dry-run` ausführen.

### 6. Abschlussprüfung

Im Stalwart-Konto `archiv@archiv.test` den Ordner `Thunderbird-Archiv`, dessen
gesamten Unterordnerbaum, Nachrichtenanzahl, Stichproben, Flags/Tags und Anhänge
prüfen. Erst nach erfolgreicher fachlicher Kontrolle über Aufräumen oder den
späteren Produktivimport sprechen. In diesem Test nichts aus der Quelle löschen.

## Arbeitsauftrag für den neuen Codex-Chat

Nicht neu entwerfen, sondern dieses Verfahren auf dem Laptop ausführen und an
den vorgesehenen Kontrollpunkten mit konkreten Zahlen berichten. Kleine
notwendige Anpassungen an Versionen oder lokalen Pfaden sind erlaubt, solange
die Sicherheitsregeln erhalten bleiben. Bei einem Warnsignal stoppen und erst
die Ursache diagnostizieren.
