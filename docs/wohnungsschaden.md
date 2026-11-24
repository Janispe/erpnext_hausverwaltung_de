# Wohnungsschäden in ERPNext Issue

## Eingang und Bearbeitung

- **E-Mail:** In der eingegangenen Communication **Als Wohnungsschaden bearbeiten** wählen. Der Vorgang übernimmt die Mail als Eingang und zeigt sie in der Timeline mit ihren Anhängen. Hat der Import die Mail bereits mit einem Issue verknüpft, wird dieses Issue weiterverwendet. Mehrmaliges Ausführen öffnet denselben Vorgang.
- **Telefon:** In der Issue-Liste **Telefon-Schaden erfassen** wählen, Betreff und Telefonnotiz eintragen und speichern. Der Eingang kann zunächst ohne Immobilie, Wohnung oder Vertrag erfasst werden.
- **Zuordnung:** Wohnung auswählen. Die Immobilie ergibt sich daraus. Den Mietvertrag erst nach fachlicher Klärung ausdrücklich auswählen. Das Formular bietet die Verträge der gewählten Wohnung an. Die Validierung prüft Wohnung und Vertrag erneut. Der Customer kommt aus dem bestätigten Vertrag. Ohne Vertrag bleibt das Customer-Feld leer.
- **Bearbeitung:** Zuständige Person, Handwerksbetrieb, Termin und Wiedervorlage im Abschnitt **Wohnungsschaden** eintragen. Die Issue-Liste kann nach Wiedervorlage gefiltert werden. Einen vorhandenen Anlagenmangel oder Versicherungsfall bei Bedarf verknüpfen.
- **Abschluss:** Rückmeldung des Handwerksbetriebs erfassen und den Issue-Status auf **Resolved** oder **Closed** setzen. In **Wohnung** und **Mietvertrag** öffnet **Wohnungsschäden** die zugehörigen Vorgänge einschließlich abgeschlossener Schäden.

## Rollen und Dateien

Die Bearbeitung ist für interne Benutzer mit **Hausverwalter** oder **System Manager** vorgesehen. Zusätzlich gelten die vorhandenen Issue-Berechtigungen der Site. Mitarbeitende brauchen Lesen, Anlegen und Schreiben auf Issue sowie Leserechte auf die verknüpften Immobilien, Wohnungen, Verträge und gegebenenfalls Anlagenmängel und Versicherungsfälle. Die Rechte werden im Rollenberechtigungsmanager der jeweiligen Site verwaltet. Beim E-Mail-Eingang braucht der Benutzer Leserechte auf der Communication und Schreibrechte auf dem bereits verknüpften Issue oder auf der unverknüpften Communication.

Fotos über **Anhänge** am gespeicherten Issue hochladen. Frappe speichert diese Dateien privat. Auch die mit der Eingangsmail übernommenen Anhänge bleiben beim Quelldokument und unterliegen den Rechten des zugeordneten Vorgangs. Für bereits öffentliche Mailanhänge vor der Übernahme die Sichtbarkeit auf **Privat** umstellen und gegebenenfalls bestehende Dokumentfreigaben entfernen. Schäden, zugehörige Communications und ihre Anhänge werden über Rollen und Objektrechte freigegeben. Im Kundenportal bleiben sie ausgeblendet.
