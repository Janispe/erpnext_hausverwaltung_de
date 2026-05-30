// action-handlers.js — Action-Dispatcher für die Modals.
//
// Die React-Modals (op-actions.jsx) feuern beim "Bestätigen"-Klick ein Event
// auf window.OP_ACTIONS — der ruft den passenden Frappe-Endpoint.
//
// Die Endpoints erzeugen Draft-Belege. Submit/Buchung erfolgt anschließend
// bewusst im ERPNext-Desk.

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
      `Mahnung ${result.dunning} als Draft erstellt · ${frappe.format(result.summe, { fieldtype: "Currency" })}`,
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
    handleResult(result, `${(result.created || []).length} Mahnungen als Draft erstellt`);
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
    handleResult(result, `Payment Entry ${result.payment_entry} als Draft erstellt`);
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Mieter-Guthaben auszahlen ─────────────────────────────────────────
  async function createRefundPayment(row, opts = {}) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_refund_payment",
      {
        sales_invoice: row.belegnummer,
        posting_date: opts.postingDate,
        bank_account: opts.bankAccount || null,
        mode_of_payment: opts.modeOfPayment || "Bank Draft",
      },
    );
    handleResult(result, `Auszahlung ${result.payment_entry} als Draft erstellt`);
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
      `Payment Reconciliation ${result.payment_reconciliation} als Draft vorbereitet · Rest ${frappe.format(result.rest, { fieldtype: "Currency" })}`,
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
    handleResult(result, `Abschreibung als Journal Entry Draft erstellt · ${result.journal_entry}`);
    await window.OP_ADAPTER.refresh({});
    return result;
  }

  // ─── Stundung dokumentieren ─────────────────────────────────────────────
  async function setStundungComment(row, opts = {}) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.set_stundung_comment",
      {
        sales_invoice: row.belegnummer,
        grund: opts.grund || "Stundung vereinbart",
        notiz: opts.notiz || "",
        stundung_bis: opts.stundungBis || null,
      },
    );
    toast(`Stundung an ${row.belegnummer} dokumentiert`);
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
    createRefundPayment,
    allocatePayment,
    writeOff,
    setStundungComment,
    openMieterkonto,
    openBeleg,
  };
})();
