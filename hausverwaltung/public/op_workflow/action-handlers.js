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

  async function listDunningTypes() {
    const result = await call("hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.list_dunning_types", {});
    return Array.isArray(result) ? result : [];
  }

  async function listSerienbriefVorlagen() {
    const result = await call("hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.list_serienbrief_vorlagen", {
      doctype: "Dunning",
    });
    return Array.isArray(result) ? result : [];
  }

  async function getSerienbriefVorlageVariables(template, dunningType, context = {}) {
    if (!template) return { template: null, variables: [] };
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_serienbrief_vorlage_variables",
      {
        template,
        dunning_type: dunningType || null,
        sales_invoices: context.salesInvoices || context.sales_invoices || null,
        mahngebuehr: context.mahngebuehr ?? null,
      },
    );
    return result || { template, variables: [] };
  }

  async function getSerienbriefValueFields(template, dunningType, context = {}) {
    if (!template) return { template: null, fields: [] };
    const result = await call(
      "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_serienbrief_value_fields",
      {
        template,
        iteration_doctype: "Dunning",
        context: {
          dunning_type: dunningType || null,
          sales_invoices: context.salesInvoices || context.sales_invoices || null,
          mahngebuehr: context.mahngebuehr ?? null,
        },
      },
    );
    return result || { template, fields: [] };
  }

  // ─── Einzel-Mahnung ─────────────────────────────────────────────────────
  async function createDunning(row, opts) {
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_dunning",
      {
        sales_invoice: row.belegnummer,
        dunning_type: opts.dunningType,
        posting_date: opts.briefdatum || null,
        mahngebuehr: opts.mahngebuehr,
        zinsen_aktiv: opts.zinsenAktiv,
        serienbrief_vorlage: opts.serienbriefVorlage || null,
        serienbrief_werte: opts.serienbriefWerte || null,
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
    const dunningTypePerCustomer = {};
    const mahngebuehrPerCustomer = {};
    const serienbriefVorlagePerCustomer = {};
    const serienbriefWertePerCustomer = {};
    for (const [party, rows] of Object.entries(rowsByParty)) {
      invoicesByCustomer[party] = rows.map((r) => r.belegnummer);
      if (opts?.dunningType) dunningTypePerCustomer[party] = opts.dunningType;
      if (opts?.mahngebuehrPerParty && Object.prototype.hasOwnProperty.call(opts.mahngebuehrPerParty, party)) {
        mahngebuehrPerCustomer[party] = opts.mahngebuehrPerParty[party];
      } else if (opts?.mahngebuehr !== undefined) {
        mahngebuehrPerCustomer[party] = opts.mahngebuehr;
      }
      if (opts?.serienbriefVorlage) serienbriefVorlagePerCustomer[party] = opts.serienbriefVorlage;
      else if (rows[0]?.serienbrief_vorlage) serienbriefVorlagePerCustomer[party] = rows[0].serienbrief_vorlage;
      if (opts?.serienbriefWerte) serienbriefWertePerCustomer[party] = opts.serienbriefWerte;
    }
    const result = await call(
      "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.create_bulk_dunning",
      {
        invoices_by_customer: invoicesByCustomer,
        dunning_type_per_customer: dunningTypePerCustomer,
        mahngebuehr_per_customer: mahngebuehrPerCustomer,
        zinsen_aktiv: opts?.zinsenAktiv !== undefined ? opts.zinsenAktiv : true,
        serienbrief_vorlage_per_customer: serienbriefVorlagePerCustomer,
        serienbrief_vorlage: opts?.serienbriefVorlage || null,
        serienbrief_werte_per_customer: serienbriefWertePerCustomer,
        serienbrief_werte: opts?.serienbriefWerte || null,
        posting_date: opts.briefdatum || null,
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

  function openSingleBeleg(doctype, voucherName) {
    frappe.set_route("Form", doctype, voucherName);
  }

  function openBeleg(row) {
    const doctypeMap = {
      "Sales Invoice": "Sales Invoice",
      "Purchase Invoice": "Purchase Invoice",
      "Payment Entry": "Payment Entry",
      "Journal Entry": "Journal Entry",
    };
    const dt = doctypeMap[row.belegart] || row.belegart.replace(/ \(×\d+\)$/, "");
    const voucherNames = Array.isArray(row.member_voucher_nos) && row.member_voucher_nos.length
      ? row.member_voucher_nos
      : [row.belegnummer];
    if (voucherNames.length > 1) {
      frappe.prompt([
        {
          fieldname: "voucher_name",
          fieldtype: "Select",
          label: "Beleg",
          options: voucherNames.join("\n"),
          default: voucherNames.includes(row.belegnummer) ? row.belegnummer : voucherNames[0],
          reqd: 1,
        },
      ], (values) => {
        openSingleBeleg(dt, values.voucher_name);
      }, `${dt} auswählen`, "Öffnen");
      setTimeout(() => {
        const dialog = document.querySelector(".modal.show");
        const primary = dialog?.querySelector(".modal-footer .btn-primary");
        if (primary) primary.focus();
      });
      return;
    }
    openSingleBeleg(dt, row.belegnummer);
  }

  function openDunning(name) {
    if (!name) return;
    frappe.set_route("Form", "Dunning", name);
  }

  function openDunningPdf(name) {
    if (!name) return;
    const params = new URLSearchParams({
      doctype: "Dunning",
      name,
      format: "HV Dunning Letter",
      no_letterhead: "0",
    });
    window.open(`/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`, "_blank");
  }

  // ─── Public API ─────────────────────────────────────────────────────────
  window.OP_ACTIONS = {
    listDunningTypes,
    listSerienbriefVorlagen,
    getSerienbriefVorlageVariables,
    getSerienbriefValueFields,
    createDunning,
    createBulkDunning,
    createPaymentEntry,
    createRefundPayment,
    allocatePayment,
    writeOff,
    setStundungComment,
    openMieterkonto,
    openBeleg,
    openDunning,
    openDunningPdf,
  };
})();
