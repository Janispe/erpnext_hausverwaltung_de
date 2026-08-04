# Arbeitsregeln für Coding-Agenten

## Zentrale Domäneninvariante: Customer, Mietvertrag und Wohnung

In dieser Anwendung ist ein ERPNext-`Customer` **nicht** die allgemeine
Personenidentität eines Mieters. Er ist die buchhalterische Debitoren-Entität
genau eines `Mietvertrag`. Die Zuordnung `Mietvertrag` ↔ `Customer` ist in beide
Richtungen **1:1**.

- Jeder Mietvertrag hat genau einen eigenen Customer; jeder Customer gehört
  genau einem Mietvertrag und damit genau einer Wohnung.
- Einen Customer niemals für einen zweiten Mietvertrag wiederverwenden, auch
  nicht für dieselbe Wohnung oder dieselbe Person.
- Bei einem Mieterwechsel wird für das neue Mietverhältnis ein neuer `Customer`
  erzeugt. Der bisherige Customer bleibt für die historischen Buchungen erhalten.
- Eine Wohnung kann deshalb im Zeitverlauf mehrere historische Customers haben,
  aber höchstens einen aktuell dort wohnenden Customer beziehungsweise einen
  aktuell laufenden Mietvertrag.
- Mietet dieselbe natürliche oder juristische Person mehrere Wohnungen, erhält
  jedes Mietverhältnis einen eigenen Customer. Gemeinsame Personeninformationen
  werden über `Contact` und die `Vertragspartner` des Mietvertrags abgebildet.
- Buchungs-, Matching-, Mahn- und Abrechnungslogik darf nicht vorsorglich von
  „mehreren Wohnungen pro Customer“ ausgehen. Eine solche Erweiterung wäre eine
  bewusste Änderung des Domänenmodells und muss ausdrücklich beauftragt werden.
- Für die buchhalterische Identität ist der eine `Mietvertrag` mit seinen
  Feldern `kunde` und `wohnung` die maßgebliche Zuordnung. Rechnungen und
  Zahlungen sind dagegen zu validieren; Mehrdeutigkeit darf nicht durch Raten
  oder Fallbacks auf einen anderen Mietvertrag aufgelöst werden.
