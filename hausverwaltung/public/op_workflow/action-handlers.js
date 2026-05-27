// action-handlers.js — Action-Dispatcher für die Modals.
//
// Die React-Modals (op-actions.jsx) feuern beim "Bestätigen"-Klick ein Event
// auf window.OP_ACTIONS — der ruft den passenden Frappe-Endpoint.
//
// HINWEIS: Solange die Action-Bodies in op_workflow.py noch auskommentiert sind
// (Phase-3-Setup nicht abgeschlossen — Dunning Types etc.), liefert das Backend
// `{ mock: true }` zurück. handleResult() zeigt dann eine deutliche Warnung
// statt der Erfolgs-Meldung.

(function () {
  async function call(method, args) {
    try {
      const res = await frappe.call({ method, args });
      return res.message;
    } catch (err) {
      const msg = err.message || String(err);
      frappe.msgprint({
        title: __("Fehler"),
        message: msg,
        indicator: "red",
      });
      throw err;
    }
  }

  function toast(msg, kind = "green") {
    frappe.show_alert({ message: msg, indicator: kind });
  }

  function handleResult(result, successMsg) {
    if (result && result.mock) {
      toast(
        __("Backend noch im Mock-Modus. Body in op_workflow.py auskommentiert — kein echter Beleg erstellt."),
        "orange",
      );
      return;
    }
    toast(successMsg);
  }

  // ─── Einzel-Mahnung ─────────────────────────────────────────────────────
  async function createDunning(row, opts) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_dunning",
      {
        sales_invoice: row.belegnummer,
        dunning_type: opts.dunningType,
        new_due_date: opts.neueFaelligkeit,
        mahngebuehr: opts.mahngebuehr,
        zinsen_aktiv: opts.zinsenAktiv,
      },
    );
    handleResult(
      result,
      `Mahnung ${result.dunning} erstellt · ${frappe.format(result.summe, { fieldtype: "Currency" })}`,
    );
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Sammelmahnung ──────────────────────────────────────────────────────
  async function createBulkDunning(rowsByParty, opts) {
    const invoicesByCustomer = {};
    for (const [party, rows] of Object.entries(rowsByParty)) {
      invoicesByCustomer[party] = rows.map((r) => r.belegnummer);
    }
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_bulk_dunning",
      {
        invoices_by_customer: invoicesByCustomer,
        new_due_date: opts.neueFaelligkeit,
      },
    );
    if (result.errors && result.errors.length) {
      result.errors.forEach((e) => toast(`Fehler bei ${e.customer}: ${e.msg}`, "red"));
    }
    handleResult(result, `${(result.created || []).length} Mahnungen erstellt`);
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Zahlung anlegen (Lieferanten-Rechnung) ─────────────────────────────
  async function createPaymentEntry(row, opts) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_payment_entry",
      {
        purchase_invoice: row.belegnummer,
        posting_date: opts.zahldatum,
        use_skonto: opts.useSkonto,
        skonto_amount: opts.skontoAmount,
        mode_of_payment: opts.zahlart,
      },
    );
    handleResult(result, `Payment Entry ${result.payment_entry} erstellt`);
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Vorauszahlung zuordnen ─────────────────────────────────────────────
  async function allocatePayment(row, allocations) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.allocate_payment",
      {
        payment_entry: row.belegnummer,
        allocations,
      },
    );
    handleResult(
      result,
      `${result.allocated} Zuordnungen gebucht · Rest ${frappe.format(result.rest, { fieldtype: "Currency" })}`,
    );
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Abschreiben ────────────────────────────────────────────────────────
  async function writeOff(row, opts = {}) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.write_off_invoice",
      {
        sales_invoice: row.belegnummer,
        remarks: opts.remarks,
      },
    );
    handleResult(result, `Abgeschrieben · JE ${result.journal_entry}`);
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Navigations-Aktionen ───────────────────────────────────────────────
  function openMieterkonto(row) {
    window.location.href = "/app/mieterkonto-workflow?customer=" + encodeURIComponent(row.party);
  }

  function openBeleg(row) {
    const doctypeMap = {
      "Sales Invoice": "Sales Invoice",
      "Purchase Invoice": "Purchase Invoice",
      "Payment Entry": "Payment Entry",
      "Journal Entry": "Journal Entry",
    };
    const dt = doctypeMap[row.belegart] || row.belegart.replace(/ \(×\d+\)$/, "");
    frappe.set_route("Form", dt, row.belegnummer);
  }

  // ─── Public API ─────────────────────────────────────────────────────────
  window.OP_ACTIONS = {
    createDunning,
    createBulkDunning,
    createPaymentEntry,
    allocatePayment,
    writeOff,
    openMieterkonto,
    openBeleg,
  };
})();
