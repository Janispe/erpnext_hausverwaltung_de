# Dokumentvorlagen Import

Importiert alte Dokumentvorlagen aus TXT-Dateien in Frappe Serienbrief-Vorlagen.

## Voraussetzungen

- Ordner `import/export_dokumentvorlagen_txt/` mit TXT-Dateien

## Verwendung

### Einfach mit Bash-Script

```bash
cd /path/to/hausverwaltung
./import_dokumentvorlagen.sh
```

Das Script fragt nach:
- Site-Name
- Dry-Run (zum Testen ohne Änderungen)

### Dry-Run (Vorschau ohne Änderungen)

Zuerst einen Testlauf machen, um zu sehen was importiert würde:

```bash
bench --site [sitename] console
```

Dann in der Console:
```python
from hausverwaltung.hausverwaltung.data_import.import_dokumentvorlagen import import_dokumentvorlagen
import_dokumentvorlagen(dry_run=True)
```

### Echter Import

```bash
bench --site [sitename] execute hausverwaltung.hausverwaltung.data_import.import_dokumentvorlagen.import_dokumentvorlagen
```

## Optionen

```python
from hausverwaltung.hausverwaltung.data_import.import_dokumentvorlagen import import_dokumentvorlagen

# Standard: Kategorie "Dokumentvorlagen Import", Iterations-Doctype "Mietvertrag"
import_dokumentvorlagen()

# Custom Kategorie
import_dokumentvorlagen(kategorie_name="Meine Kategorie")

# Custom Iterations-Doctype
import_dokumentvorlagen(kategorie_name="Import", default_iteration_doctype="Contact")

# Custom Quellordner
import_dokumentvorlagen(source_dir="/pfad/zu/meinen/vorlagen")

# Platzhalter-Ersetzung deaktivieren
import_dokumentvorlagen(replace_variables=False)
```

## Was macht das Tool?

1. **Liest alle TXT-Dateien** aus `import/export_dokumentvorlagen_txt/`
2. **Extrahiert den Titel** aus dem Dateinamen (Format: `DOKUMENTVORLAGEN_<ID>_<Titel>.txt`)
3. **Bereinigt den Text**: Entfernt binäre Formatierungsdaten am Ende der Dateien
4. **Ersetzt Platzhalter**: Wandelt alte Platzhalter in Jinja-Variablen um (siehe unten)
5. **Erstellt Serienbrief-Vorlagen** mit dem bereinigten Text als `content`
6. **Aktualisiert bestehende Vorlagen**: Nur wenn das `content` Feld leer ist

## Dateiformat

Die Dateien haben folgendes Format:
- Dateiname: `DOKUMENTVORLAGEN_<ID>_<Titel>.txt`
- Beispiel: `DOKUMENTVORLAGEN_10_1 Mahnung.txt` → Titel: "1 Mahnung"

## Platzhalter-Mapping

Die alten Platzhalter (z.B. `«Verw.-Name»`, `«B-Anrede1»`) werden **automatisch** auf neue Jinja-Variablen gemappt!

Das Tool ersetzt über 50 gängige Platzhalter:

### Bewohner/Mieter
- `«B-Name1»` → `{{ mieter[0].last_name if mieter else '' }}`
- `«B-Vorname1»` → `{{ mieter[0].first_name if mieter else '' }}`
- `«B-PLZ-Ort»` → `{{ (address.pincode or '') + ' ' + (address.city or '') if address else '' }}`
- `«B-Saldo»` → `{{ saldo if saldo else '' }}`
- `«B-Einzug»` → `{{ mietvertrag.von if mietvertrag else '' }}`
- `«B-Auszug»` → `{{ mietvertrag.bis if mietvertrag else '' }}`

### Verwalter
- `«Verw.-Name»` → `{{ verwalter.name if verwalter else 'Hausverwaltung' }}`
- `«Verw.-Straße»` → `{{ verwalter.address_line1 if verwalter else 'Tristanstr. 4' }}`
- `«Systemdatum»` → `{{ frappe.utils.formatdate(frappe.utils.nowdate(), 'dd.MM.yyyy') }}`

### Eigentümer
- `«E-Name1»` → `{{ eigentuemer.last_name if eigentuemer else '' }}`
- `«E-Vorname1»` → `{{ eigentuemer.first_name if eigentuemer else '' }}`
- `«E-Saldo»` → `{{ eigentuemer_saldo if eigentuemer_saldo else '' }}`

### Wohnung/Immobilie
- `«Whg-Bez»` → `{{ wohnung.name if wohnung else '' }}`
- `«H-Bezeichnung»` → `{{ immobilie.name if immobilie else '' }}`

Und viele mehr! Siehe [placeholder_mapping.py](placeholder_mapping.py) für die vollständige Liste.

### Platzhalter-Ersetzung testen

```bash
cd hausverwaltung/hausverwaltung/data_import
python3 test_placeholder_replacement.py
```

### Platzhalter-Ersetzung deaktivieren

```python
import_dokumentvorlagen(replace_variables=False)  # Platzhalter bleiben original
```

## Beispiel-Ersetzung

**Vorher:**
```
«Verw.-Name», «Verw.-Straße», «Verw.-PLZ_Ort»
«B-Anrede1» «B-Vorname1» «B-Name1»

München, «Systemdatum»

Sehr geehrte/r «B-Brief_Anrede1» «B-Name1»,
Ihr Saldo beträgt: «B-Saldo»
```

**Nachher:**
```
{{ verwalter.name if verwalter else 'Hausverwaltung' }}, {{ verwalter.address_line1 if verwalter else 'Musterstr. 1' }}, {{ verwalter.plz_ort if verwalter else '12345 Musterstadt' }}
{{ mieter[0].salutation if mieter else '' }} {{ mieter[0].first_name if mieter else '' }} {{ mieter[0].last_name if mieter else '' }}

München, {{ frappe.utils.formatdate(frappe.utils.nowdate(), 'dd.MM.yyyy') }}

Sehr geehrte/r {{ mieter[0].salutation if mieter else '' }} {{ mieter[0].last_name if mieter else '' }},
Ihr Saldo beträgt: {{ saldo if saldo else '' }}
```

## Hinweise

- Es werden **412 Dokumentvorlagen** importiert
- Bestehende Vorlagen mit gleichem Titel werden **nicht überschrieben** (nur ergänzt wenn leer)
- Dateien mit unlesbarem Inhalt werden übersprungen
- Der Import ist **idempotent** (kann mehrmals ausgeführt werden)
- Standard Kategorie: "Dokumentvorlagen Import"
- Standard Iterations-Doctype: "Mietvertrag"
