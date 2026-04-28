frappe.query_reports["euer"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Firma"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company"),
      reqd: 1
    },
    {
      fieldname: "immobilie",
      label: __("Immobilie"),
      fieldtype: "Link",
      options: "Immobilie",
      reqd: 0,
      on_change: () => {
        frappe.query_report.set_filter_value("konten", []);
      }
    },
    {
      fieldname: "konten",
      label: __("Konten"),
      fieldtype: "MultiSelectList",
      get_data: function (txt) {
        return frappe.call({
          method: "hausverwaltung.hausverwaltung.report.euer.euer.get_account_filter_options",
          args: {
            txt: txt,
            company: frappe.query_report.get_filter_value("company"),
            immobilie: frappe.query_report.get_filter_value("immobilie")
          }
        }).then((r) => r.message || []);
      }
    },
    {
      fieldname: "from_date",
      label: __("Von"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.year_start()
    },
    {
      fieldname: "to_date",
      label: __("Bis"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.year_end()
    },
    {
      fieldname: "show_details",
      label: __("Alle Buchungen anzeigen"),
      fieldtype: "Check",
      default: 0
    },
    {
      fieldname: "include_non_euer_accounts",
      label: __("Nicht‑EÜR Konten anzeigen (separat)"),
      fieldtype: "Check",
      default: 0
    },
    {
      fieldname: "umlage_method",
      label: __("Umlagefähig trennen über"),
      fieldtype: "Select",
      options: "Kontenstruktur\nKostenarten",
      default: "Kontenstruktur"
    },
    {
      fieldname: "show_bank_check",
      label: __("Bank/Kasse Abgleich anzeigen"),
      fieldtype: "Check",
      default: 0
    }
  ],

  formatter: function(value, row, column, data, default_formatter) {
    value = default_formatter(value, row, column, data);

    // Fettdruck für Summenzeilen
    if (data && data.bold) {
      value = `<span style="font-weight: bold;">${value}</span>`;
    }

    return value;
  }
};
