# WIRING — React-Modals → Action-Handlers

Diese Datei dokumentiert die *eine* Code-Änderung, die du in `op-app.jsx`
machen musst, damit die Modals in Produktion tatsächlich `window.OP_ACTIONS`
aufrufen statt nur Toasts zu zeigen.

Im Studio-Mockup haben die Modals `onClose`-Handler, die den Modal schließen
und einen Toast zeigen. In Produktion sollen sie *zusätzlich* eine echte
Frappe-Aktion auslösen.

## Stelle in `op-app.jsx`

Such die Sektion:

```jsx
{/* Modals */}
{modal?.type === "mahnung" && <MahnungModal ... />}
{modal?.type === "sammelmahnung" && <SammelmahnungModal ... />}
{modal?.type === "zahlung" && <ZahlungModal ... />}
{modal?.type === "zuordnen" && <ZuordnenModal ... />}
```

## Vorher (Studio-Modus)

```jsx
{modal?.type === "mahnung" && (
  <MahnungModal row={modal.row}
    onClose={() => {
      setModal(null);
      setToast(`Mahnung gesendet an ${window.OFFENE_POSTEN.partyName(modal.row.party)}`);
    }} />
)}
```

## Nachher (mit OP_ACTIONS-Bridge)

```jsx
{modal?.type === "mahnung" && (
  <MahnungModal row={modal.row}
    onConfirm={async (opts) => {
      // Echte Aktion auslösen (Mock oder real, je nach action-handlers.js)
      await window.OP_ACTIONS.createDunning(modal.row, opts);
      setModal(null);
    }}
    onCancel={() => setModal(null)} />
)}
```

Für jeden Modal-Typ analog:
- `mahnung` → `OP_ACTIONS.createDunning(row, opts)`
- `sammelmahnung` → `OP_ACTIONS.createBulkDunning(rowsByParty, opts)`
- `zahlung` → `OP_ACTIONS.createPaymentEntry(row, opts)`
- `zuordnen` → `OP_ACTIONS.allocatePayment(row, allocations)`

## Im jeweiligen Modal (in `op-actions.jsx`)

Den `onClose`-Prop ersetzen durch `onConfirm` + `onCancel`. Beispiel
MahnungModal:

```jsx
function MahnungModal({ row, onConfirm, onCancel }) {
  // ... bestehender State ...

  return (
    <Modal title="..." onClose={onCancel} footer={
      <>
        <button onClick={onCancel}>Abbrechen</button>
        <button onClick={() => onConfirm({
          dunningType: textStufe,
          neueFaelligkeit,
          mahngebuehr,
          zinsenAktiv: zinsen,
        })}>
          {`Mahnung versenden · ${fmtEUR_op(summe)}`}
        </button>
      </>
    }>
      {/* ... bestehende Form ... */}
    </Modal>
  );
}
```

## Übergangs-Strategie (empfohlen)

Mach beides parallel: alter `onClose`-Pfad bleibt, *zusätzlich* checke ob
`window.OP_ACTIONS` existiert und ruf es auf. So funktioniert das Studio-Mockup
weiterhin offline, und in der Frappe-Page wird automatisch der echte Pfad
genommen.

```jsx
const handleConfirm = async (opts) => {
  if (window.OP_ACTIONS) {
    await window.OP_ACTIONS.createDunning(modal.row, opts);
  } else {
    setToast(`Mahnung gesendet an ${window.OFFENE_POSTEN.partyName(modal.row.party)}`);
  }
  setModal(null);
};
```
