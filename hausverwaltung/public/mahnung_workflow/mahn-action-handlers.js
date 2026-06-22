// mahn-action-handlers.js — Bridge: "Erzeugen & versenden" → echte Frappe-Aktion.
//
// PHASE 1/2: USE_MOCK_ACTIONS.dunning = true → nur die Mock-Bestätigung im UI.
// PHASE 3:   auf false setzen → ruft mahnung_workflow.create_dunning() per frappe.call.
//
// mahn-app.jsx ruft window.MAHN_ACTIONS.createDunning(payload) auf, FALLS vorhanden.
// Solange dieses Objekt fehlt (reines Studio-Mockup), bleibt es beim lokalen Mock.
//
// payload (aus mahn-app.jsx zusammengebaut):
//   {
//     party, vorlageKey, tpl_id, mahndatum, fristTage, kanal,
//     belege: ["ACC-SINV-..."], mahngebuehr, zinssatz, zinsenAktiv,
//     kontonummer, variablen: { ... }, summe
//   }

(function () {
  const USE_MOCK_ACTIONS = {
    dunning: true, // ⚠ PHASE 3: auf false setzen, wenn echte Mahnungen laufen
  };

  const METHOD = "hausverwaltung.hausverwaltung.page.mahnung_workflow.mahnung_workflow";

  window.MAHN_ACTIONS = {
    async createDunning(payload) {
      if (USE_MOCK_ACTIONS.dunning) {
        // Mock: dieselben Felder zurückgeben, die das Sent-Overlay erwartet.
        return {
          dunning: "DUN-MOCK-001",
          summe: payload.summe,
          docs: [
            { id: "DUN-MOCK-001", desc: `Dunning-Doc · ${payload.tpl_id || payload.vorlageKey}`, amount: payload.summe },
          ],
          mock: true,
        };
      }
      const res = await frappe.call({
        method: `${METHOD}.create_dunning`,
        args: {
          sales_invoices: JSON.stringify(payload.belege),
          dunning_type: payload.vorlageKey,
          posting_date: payload.mahndatum,
          frist_tage: payload.fristTage,
          mahngebuehr: payload.mahngebuehr,
          zinsen_aktiv: payload.zinsenAktiv ? 1 : 0,
          kanal: payload.kanal,
        },
      });
      return res.message;
    },
  };
})();
