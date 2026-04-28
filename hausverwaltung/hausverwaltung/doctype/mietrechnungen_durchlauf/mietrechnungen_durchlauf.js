function show_mietrechnungen_dialog() {
  const today = frappe.datetime.get_today();
  const default_month = parseInt(today.slice(5, 7), 10);
  const default_year = parseInt(today.slice(0, 4), 10);

  const dlg = new frappe.ui.Dialog({
    title: "Mietrechnungen erstellen",
    fields: [
      {
        fieldname: "company",
        label: "Company",
        fieldtype: "Link",
        options: "Company",
        reqd: 1,
        default: frappe.defaults.get_user_default("Company") || frappe.defaults.get_global_default("company"),
      },
      {
        fieldname: "monat",
        label: "Monat",
        fieldtype: "Select",
        options: "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12",
        reqd: 1,
        default: String(default_month),
      },
      {
        fieldname: "jahr",
        label: "Jahr",
        fieldtype: "Int",
        reqd: 1,
        default: default_year,
      },
    ],
    primary_action_label: "Erstellen",
    primary_action(values) {
      const company = values.company;
      const monat = values.monat;
      const jahr = values.jahr;

      if (!company || !monat || !jahr) {
        frappe.msgprint(__("Bitte Company, Monat und Jahr angeben."));
        return;
      }

      frappe.call({
        method: "hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
        args: { company, monat, jahr },
        freeze: true,
        freeze_message: __("Erzeuge Mietrechnungen..."),
        callback: (r) => {
          if (r.exc) return;
          const msg = r.message;
          if (!msg) {
            frappe.msgprint(__("Fertig."));
            return;
          }
          const created = msg.created || {};
          const skipped = (msg.skipped || []).length;
          const month_label = msg.month || `${jahr}-${String(monat).padStart(2, "0")}`;
          let detail_html = "";
          const details = msg.skipped_details || [];
          const esc = frappe.utils.escape_html;
          if (details.length) {
            const max_items = 50;
            const shown = details.slice(0, max_items);
            const items = shown
              .map((d) => {
                const mv = esc(d.mietvertrag || "");
                const whg = esc(d.wohnung || "");
                const typ = esc(d.typ || "");
                const reason = esc(d.reason || "");
                const message = esc(d.message || "");
                const parts = [message];
                if (typ) parts.push(`Typ: ${typ}`);
                if (whg) parts.push(`Wohnung: ${whg}`);
                if (mv) parts.push(`Mietvertrag: ${mv}`);
                if (reason) parts.push(`Grund: ${reason}`);
                return `<li>${parts.join(" | ")}</li>`;
              })
              .join("");
            const rest = details.length - shown.length;
            const rest_note = rest > 0 ? `<li>+${rest} weitere</li>` : "";
            detail_html = `<hr><div><strong>Hinweise</strong><ul>${items}${rest_note}</ul></div>`;
          }
          const run_id = msg.durchlauf || "";
          const run_link = run_id
            ? `<div class="mt-2"><a class="btn btn-xs btn-primary" onclick="frappe.set_route('Form','Mietrechnungen Durchlauf','${esc(run_id)}')">Durchlauf öffnen</a></div>`
            : "";
          frappe.msgprint(
            __("{0} Miete, {1} BK, {2} Heiz für {3} erstellt. Übersprungen: {4}{5}{6}", [
              created.Miete || 0,
              created.Betriebskosten || 0,
              created.Heizkosten || 0,
              month_label,
              skipped,
              detail_html,
              run_link,
            ])
          );

          if (run_id) {
            dlg.hide();
            frappe.set_route("Form", "Mietrechnungen Durchlauf", run_id);
            return;
          }
          dlg.hide();
          frappe.set_route("List", "Mietrechnungen Durchlauf");
        },
      });
    },
  });

  dlg.show();
}

frappe.ui.form.on("Mietrechnungen Durchlauf", {
  refresh(frm) {
    if (frm.is_new() && !frm.__run_dialog_opened) {
      frm.__run_dialog_opened = true;
      show_mietrechnungen_dialog();
    }
  },
});
