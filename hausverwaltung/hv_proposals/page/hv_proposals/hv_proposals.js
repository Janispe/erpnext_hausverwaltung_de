frappe.pages["hv-proposals"].on_page_load = function (wrapper) {
	frappe.require(["/assets/hausverwaltung/css/hv_proposals.css", "/assets/hausverwaltung/js/hv_proposals.js"], () => {
		wrapper.hv_proposals = new hausverwaltung.hv_proposals.Inbox(wrapper);
		wrapper.hv_proposals.route();
	});
};
frappe.pages["hv-proposals"].on_page_show = function (wrapper) {
	if (wrapper.hv_proposals) wrapper.hv_proposals.route();
};
