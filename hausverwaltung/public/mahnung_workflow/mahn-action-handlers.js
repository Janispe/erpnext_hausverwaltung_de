// mahn-action-handlers.js — Bridge: "Erzeugen & versenden" → echte Frappe-Aktion.
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
  const METHOD = "hausverwaltung.hausverwaltung.page.mahnung_workflow.mahnung_workflow";

  function serializeSerienbriefWerte(payload) {
    const rows = [];
    const values = payload.variablen || {};
    Object.entries(values).forEach(([variable, wert]) => {
      if (variable) rows.push({ variable, wert });
    });
    if (payload.kontonummer) rows.push({ variable: "kontonummer", wert: payload.kontonummer });
    if (payload.fristTage != null) rows.push({ variable: "frist_tage", wert: String(payload.fristTage) });
    if (payload.mahngebuehr != null) rows.push({ variable: "mahngebuehr", wert: String(payload.mahngebuehr) });
    return rows;
  }

  window.MAHN_ACTIONS = {
    async createDunning(payload) {
      const vorlage = window.MAHNUNG?.vorlageByKey?.[payload.vorlageKey] || {};
      const dunningType = vorlage.dunning_type || payload.dunning_type || payload.vorlageKey;
      const res = await frappe.call({
        method: `${METHOD}.create_dunning`,
        args: {
          sales_invoices: JSON.stringify(payload.belege),
          dunning_type: dunningType,
          posting_date: payload.mahndatum,
          frist_tage: payload.fristTage,
          mahngebuehr: payload.mahngebuehr,
          zinsen_aktiv: payload.zinsenAktiv ? 1 : 0,
          kanal: payload.kanal,
          serienbrief_vorlage: vorlage.serienbrief_vorlage || null,
          serienbrief_werte: serializeSerienbriefWerte(payload),
          finalize: payload.finalize === false ? 0 : 1,
        },
      });
      return res.message;
    },
    async cancelDunning(dunning) {
      const res = await frappe.call({
        method: `${METHOD}.cancel_dunning`,
        args: { dunning },
      });
      return res.message;
    },
    openSerienbriefEditor(template) {
      if (!template) {
        frappe.msgprint({
          title: __("Keine Serienbrief-Vorlage"),
          message: __("Diese Mahnstufe hat keine Serienbrief-Vorlage hinterlegt."),
          indicator: "orange",
        });
        return false;
      }
      frappe.route_options = { hv_serienbrief_template: template };
      frappe.set_route("serienbrief_editor");
      return true;
    },
  };
})();
