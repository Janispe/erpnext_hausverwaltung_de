// mahn-data-adapter.js — Datenschicht zwischen Frappe-Backend und Mahnung-Editor.
//
// PHASE 1: USE_MOCK_DATA = true  → exakt die Mock-Daten aus dem Studio (data-mahnung.js)
// PHASE 2: USE_MOCK_DATA = false → baut window.MAHNUNG aus echten Frappe-Daten:
//          überfällige Sales Invoices, Dunning-Historie, Serienbrief-/Dunning-Vorlagen.
//
// Die React-Components erwarten window.MAHNUNG mit Struktur:
//   { TODAY, absender, mieter:[...], vorlagen:[...], vorlageByKey,
//     naechsteVorlageKey(stufe), zinssatzFuer(typ), BASISZINS, overdueDays(d) }
// Siehe data-mahnung.js für das exakte Schema. Bei abweichendem Backend NUR
// die build*()-Funktionen unten anpassen, nicht die Components.

(function () {
  const USE_MOCK_DATA = true; // ⚠ PHASE 2: auf false setzen

  const METHOD = "hausverwaltung.hausverwaltung.page.mahnung_workflow.mahnung_workflow";

  // ─── ROOT-ID-Shim ──────────────────────────────────────────────────────
  // mahn-app.jsx mounted auf #root — Frappe-Page hat #mahnung-workflow-root.
  function ensureRootMount() {
    const target = document.getElementById("mahnung-workflow-root");
    if (target && !document.getElementById("root")) target.id = "root";
  }

  // ─── Mock laden (Phase 1) ───────────────────────────────────────────────
  async function loadMock() {
    if (!window.MAHNUNG) {
      await new Promise((res) => {
        const s = document.createElement("script");
        s.src = "/assets/hausverwaltung/mahnung_workflow/data-mahnung.js";
        s.onload = res;
        document.head.appendChild(s);
      });
    }
  }

  // ─── Echte Daten laden (Phase 2) ────────────────────────────────────────
  // Lädt einen Mieter (aus ?party=) inkl. überfälliger Posten + Historie und
  // die verfügbaren Vorlagen. Mehrere Mieter im Switcher: party-Liste laden.
  async function loadReal() {
    const party = new URLSearchParams(location.search).get("party");

    const res = await frappe.call({
      method: `${METHOD}.get_dunning_context`,
      args: { party: party || null },
    });
    const ctx = res.message;

    // ctx liefert bereits das fertige Schema (siehe mahnung_workflow.py).
    // Falls dein Backend abweicht: hier mappen.
    window.MAHNUNG = {
      TODAY: ctx.today,
      absender: ctx.absender,
      mieter: ctx.mieter,
      vorlagen: ctx.vorlagen,
      vorlageByKey: Object.fromEntries(ctx.vorlagen.map((v) => [v.key, v])),
      naechsteVorlageKey: (stufe) =>
        stufe >= 2 ? "letzte_mahnung" : stufe === 1 ? "mahnung_2" : stufe === 0 ? "mahnung_1" : "erinnerung",
      zinssatzFuer: (typ) =>
        Math.round((ctx.basiszins + (typ === "gewerbe" ? 9 : 5)) * 100) / 100,
      BASISZINS: ctx.basiszins,
      overdueDays: (faellig) => {
        if (!faellig) return 0;
        return Math.max(0, Math.round((new Date(ctx.today) - new Date(faellig)) / 86400000));
      },
    };
  }

  window.MAHN_ADAPTER = {
    async loadInitial() {
      ensureRootMount();
      if (USE_MOCK_DATA) await loadMock();
      else await loadReal();
    },
    isMock: () => USE_MOCK_DATA,
  };
})();
