# Dateien und Dokumente

## Arbeitsumgebung

- Der persistente Workspace heißt in der Shell `/workspace`; OpenClaw nennt
  denselben Ordner `/home/node/.openclaw/workspace`. Relative Pfade bevorzugen:
  `input/` Eingaben, `output/` Ergebnisse, `scripts/` Hilfsskripte, `tasks/`
  Arbeitsstände.
- Shell und Python laufen nur in der isolierten Sandbox. Verfügbar sind Python,
  pandas, matplotlib, python-docx, openpyxl, odfpy, pypdf, ReportLab,
  LibreOffice und Tesseract (Deutsch/Englisch).
- Die Sandbox hat kein Netzwerk, 512 MiB RAM und 1 CPU; ein einzelner Befehl
  bricht nach dem konfigurierten Zeitlimit ab (Standard 120 Sekunden). Große
  Aufgaben deshalb in begrenzten Schritten verarbeiten.
- Keine Pakete zur Laufzeit installieren; fehlende Fähigkeiten dem Nutzer nennen.

## Bilder und PDFs ansehen

`view_image` ist ein natives Modellwerkzeug: für lokale Seitenbilder als echten
Toolcall mit `path` aufrufen, nicht über `exec`. Es fehlt absichtlich im
Code-Katalog; dass es dort nicht auftaucht, heißt nicht, dass es gesperrt ist.

PDF-Inhalte mit Python/pypdf oder dem PDF-Werkzeug lesen; `read` ist kein
allgemeiner PDF-Decoder. Bei Scans kann OCR Fehler enthalten: unklare Werte
nicht als bestätigte Daten behandeln.

## Dokumente bearbeiten und prüfen

Übergebene Office-Dateien zuerst als Kopie bearbeiten. Erzeugte Dokumente durch
erneutes Einlesen prüfen, bei Layoutänderungen zusätzlich per PDF-Export und
Sichtung der Seitenbilder.

## Datei als Anhang im Chat liefern

Eine `MEDIA:`-Zeile mit dem absoluten Gateway-Pfad in der finalen Antwort
genügt, z. B. `MEDIA:/home/node/.openclaw/workspace/output/brief.pdf`; dafür ist
kein Versandwerkzeug nötig. Vorher prüfen, dass die Datei existiert. Ein
Speicherpfad allein ist noch kein bestätigter Download: Übergibt der Gateway die
Datei nicht als Anhang, den Fehler nennen statt Erfolg zu melden.
