frappe.query_reports["Miete pro qm"] = {
  formatter: (value, row, column, data, default_formatter) => {
    let formatted = default_formatter(value, row, column, data);

    const isAreaColumn =
      column?.fieldname === "größe" ||
      column?.fieldname === "groesse" ||
      column?.label === "Größe" ||
      column?.label === "Groesse";

    if (isAreaColumn && formatted) {
      formatted = `${formatted} m²`;
    }

    if (data?.wohnung === "Summe") {
      return `<span style="font-weight: 600">${formatted}</span>`;
    }

    return formatted;
  },
};
