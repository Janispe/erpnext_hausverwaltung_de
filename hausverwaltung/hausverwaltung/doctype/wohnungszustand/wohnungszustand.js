frappe.ui.form.on('Wohnungszustand', {
    refresh(frm) {
    // Ensure the Zustandsschlüssel link in each child table is filtered by its Art
    set_zustandsschluessel_filters(frm);
        if (!frm.is_new()) {
            frm.add_custom_button('Nachfolgezustand erstellen', () => {
                // Dialog definieren
                let d = new frappe.ui.Dialog({
                    title: 'Nachfolgezustand erstellen',
                    fields: [
                        {
                            label: 'Ab-Datum',
                            fieldname: 'ab_datum',
                            fieldtype: 'Date',
                            reqd: true,
                            default: frappe.datetime.add_days(frm.doc.ab || frappe.datetime.nowdate(), 1)
                        }
                    ],
                    primary_action_label: 'Erstellen',
                    primary_action(values) {
                        d.hide();
                        frappe.call({
                            method: "hausverwaltung.hausverwaltung.doctype.wohnungszustand.wohnungszustand.create_follow_up_state",  // <-- anpassen!
                            args: {
                                docname: frm.doc.name,
                                ab_datum: values.ab_datum
                            },
                            callback(r) {
                                if (r.message) {
                                    frappe.set_route('Form', 'Wohnungszustand', r.message);
                                }
                            }
                        });
                    }
                });
                d.show();
            });
        }
    }
});

function set_zustandsschluessel_filters(frm) {
    // Only allow Zustandsschlüssel with Art = Boolean in zustand_bool table
    frm.set_query('zustandsschluessel', 'zustand_bool', function() {
        return { filters: { art: 'Boolean' } };
    });

    // Only allow Zustandsschlüssel with Art = Gleitkommazahl in zustand_float table
    frm.set_query('zustandsschluessel', 'zustand_float', function() {
        return { filters: { art: 'Gleitkommazahl' } };
    });

    // Only allow Zustandsschlüssel with Art = Natürliche Zahl in zustand_int table
    frm.set_query('zustandsschluessel', 'zustand_int', function() {
        return { filters: { art: 'Natürliche Zahl' } };
    });
}
