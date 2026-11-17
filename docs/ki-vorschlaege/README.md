# KI-Vorschläge: Übergabe an den Orchestrator

Stand 17.11.2026. Unterlagen, um PR #44 (`ao/ki-vorschlaege/mvp`, synthetischer Pilot für Vorschläge und
Freigaben) weiterzuentwickeln und eine neue Prüfer-Oberfläche zu bauen.

| Datei | Inhalt |
|---|---|
| [backend.md](backend.md) | Änderungen an PR #44: Review-Nachbesserungen, Paket-Objekt, Metadaten, Graph-API |
| [oberflaeche.md](oberflaeche.md) | Prüfer-Oberfläche „Pakete mit Graph“ |
| [issues.md](issues.md) | Zwei Aufträge für den Orchestrator, mit Startbefehlen |
| [mockup/](mockup/) | Referenz-Markup aus dem Design-Canvas (Artboards B1 und B2) |

## Ablauf

1. **Backend** (Auftrag 1): PR gestapelt auf PR #44, also gegen `ao/ki-vorschlaege/mvp`.
2. **Oberfläche** (Auftrag 2): PR gestapelt auf den Backend-PR.
3. **Prüfung:**
   - Review von Code und Design gegen diese Unterlagen
   - Tests in einem isolierten Stack, nicht auf der Dev-Site 8090
   - zusätzlich das native Review im Orchestrator
4. **Merge** durch Janis, von oben nach unten: Oberfläche in Backend, Backend in PR #44, PR #44 in die
   Hauptlinie.

## Verhältnis zu den Projektregeln

Die Regeln von `hv-native-rootless` (`~/dev/hv-agent-pilot/tools/native/configure.py`) gelten weiter, mit
einer Ausnahme, die Janis beim Start ausdrücklich nennt:

- **Basis:** Die Regeln verlangen Branch und PR von `codex/agent-loop-base`. Hier ist die Basis PR #44
  beziehungsweise der Backend-PR.
- **`[skip ci]`** bleibt wie in den Regeln. Nachweis ist die lokale CI mit Rootless Docker; die Protokolle
  kommen als Artefakt in die Sitzung.
- **Start:** Issue-Texte gelten nach den Regeln als nicht vertrauenswürdig, und die automatische Aufnahme
  würde vom falschen Branch starten. Deshalb Issues ohne Zuweisung anlegen und den Worker mit `hv-ao spawn`
  direkt starten (Befehle in [issues.md](issues.md)).

## Offene Entscheidungen

1. **Hauptlinie:** PR #44 baut auf `b069558a` auf; auf `origin` liegt dazu `review/base-b069558a`.
   `codex/agent-loop-base` enthält den Integrationsstand vom 12.11. nicht; gegen diese Basis wären es
   237 Dateien statt 35. Vor dem Merge muss feststehen, in welche Linie PR #44 am Ende geht.
2. **Installation:** Modul, DocTypes, Seite und der `before_migrate`-Hook kommen auf jede Site, obwohl die
   API per `hv_proposals_synthetic_enabled` aus ist. So lassen oder erst bei Aktivierung installieren?
3. **Sammelfreigabe:** Der Entwurf erlaubt „Offene freigeben …“. Jede Freigabe bleibt einzeln an Revision
   und Hash gebunden, der Prüfer sieht aber nicht jeden Vorschlag einzeln an. Gewollt?
4. **Bearbeiter und Reviewer:** Codex oder Claude Code. Der Orchestrator kann beides, je Start mit
   `--harness` oder dauerhaft mit `hv-ao project set-config hv-native-rootless --worker-agent …` bzw.
   `--reviewer …`. Für Claude braucht der Benutzer `hv-agent` einen eigenen Login.

## Zum Mockup-Format

Die Dateien in `mockup/` stammen aus einem Design-Canvas und laufen nicht direkt im Browser:

- `{{ … }}` sind Platzhalter.
- `<sc-for>` und `<sc-if>` sind Schleifen und Bedingungen.
- Die Zustandslogik steht im `<script type="text/x-dc">` am Ende.
- `ds/hausverwaltung/…` verweist auf die Stylesheets des Design Systems; dieselben Klassen gibt es im Repo
  als `hausverwaltung/public/css/hv-tokens.css` und `hv-components.css`.

Brauchbar sind sie als Referenz für Aufbau, Abstände, Texte, Zustände und das Verhalten beim Freigeben,
Ablehnen und Ausführen. Alle Namen, Adressen und Beträge sind fiktiv. Der Canvas selbst ist privat und nur
für Janis erreichbar: https://claude.ai/artifact/4NqFhc3aQoEnZsVjdtst7i
