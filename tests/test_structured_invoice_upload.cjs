const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = readFileSync(path.join(__dirname, "../hausverwaltung/public/js/buchen_cockpit.js"), "utf8");
const inboxPage = JSON.parse(readFileSync(path.join(__dirname,
	"../hausverwaltung/hausverwaltung/page/buchungs_inbox/buchungs_inbox.json"), "utf8"));
const flush = () => new Promise((resolve) => setImmediate(resolve));

class Element {
	constructor(props = {}) {
		this.props = props;
		this.children = [];
		this.visible = true;
	}
	on(_event, click) { this.click = click; return this; }
	show() { this.visible = true; return this; }
	hide() { this.visible = false; return this; }
	html(markup) { this.markup = markup; return this; }
	get() { return this; }
	appendTo(parent) {
		this.container = parent;
		parent.children.push(this);
		return this;
	}
	replaceWith(element) {
		const children = this.container.children;
		children[children.indexOf(this)] = element;
	}
}

function uploadHarness() {
	const dialogs = [];
	const calls = [];
	const elements = new Map();
	const parent = new Element();
	const invoice = {
		profile: "XRECHNUNG", number: "R-42", date: "2026-11-24", due_date: "2026-12-08", currency: "EUR",
		net: 100, tax: 19, gross: 119, digest: "example", warnings: [],
		taxes: [{ amount: 19, rate: 19 }],
		lines: [{ name: "Arbeit", quantity: 1, net: 100, tax_rate: 19 }],
	};
	let uploader;
	class Dialog {
		constructor(options) {
			this.options = options;
			this.$body = {
				find(selector) {
					if (!elements.has(selector)) {
						const element = new Element();
						element.parent = () => parent;
						elements.set(selector, element);
					}
					return elements.get(selector);
				},
			};
			dialogs.push(this);
		}
		show() { this.visible = true; }
		hide() { this.visible = false; }
		enable_primary_action() {}
		disable_primary_action() {}
		get_value() { return false; }
	}
	const cockpit = {};
	vm.runInNewContext(script, {
		hausverwaltung: { buchen_cockpit: cockpit },
		__: (label, values = []) => label.replace("{0}", values[0] || ""),
		$: (_tag, props) => new Element(props),
		frappe: {
			provide() {},
			get_route: () => ["buchen_cockpit"],
			utils: { escape_html: String },
			ui: { Dialog, FileUploader: class { constructor(options) { uploader = options; } } },
			call({ method, args }) {
				calls.push({ method, args });
				const results = {
					bulk_create_vorschlaege: { session_id: "BS-1" },
					preview_structured_invoice: invoice,
					create_structured_invoice: { name: "PI-1" },
				};
				return Promise.resolve({ message: results[method.split(".").pop()] });
			},
		},
	});
	cockpit.open_bulk_upload_dialog();
	return { dialogs, calls, elements, parent, uploader };
}

for (const pdfFirst of [false, true]) {
	test(`mixed upload stays open when ${pdfFirst ? "PDF analysis" : "draft saving"} runs first`, async () => {
		const { dialogs, calls, elements, parent, uploader } = uploadHarness();
		const [upload] = dialogs;
		const list = elements.get(".hv-structured-uploaded-list");
		const pdf = elements.get(".hv-bulk-uploaded-list");
		uploader.on_success({ file_url: "/private/files/CII.xml", file_name: "CII.xml", invoice_format: "cii" });
		uploader.on_success({ file_url: "/private/files/second.pdf", file_name: "second.pdf", invoice_format: "cii" });
		uploader.on_success({ file_url: "/private/files/normal.pdf", file_name: "normal.pdf", invoice_format: "pdf" });

		async function queuePdf() {
			upload.options.primary_action();
			await flush();
			assert.equal(parent.children[0].props.href, `/app/${inboxPage.page_name}`);
			assert.equal(parent.children[0].visible, true);
			assert.doesNotMatch(pdf.markup, /normal\.pdf/);
			assert.equal(upload.visible, true);
		}
		async function saveDraft() {
			list.children[0].click();
			await flush();
			const [, preview] = dialogs;
			assert.match(preview.options.fields[0].options, /Fällig am 2026-12-08/);
			preview.options.primary_action({
				company: "Firma", supplier: "Lieferant", typ_0: "Umlegbar", umlegbar_0: "Reinigung",
				kostenstelle_0: "Objekt", tax_0: "Vorsteuer",
			});
			await flush();
			assert.equal(preview.visible, false);
			assert.equal(upload.visible, true);
			assert.equal(list.children[0].props.href, "/app/purchase-invoice/PI-1");
			assert.match(list.children[1].props.text, /second\.pdf/);
		}
		if (pdfFirst) {
			await queuePdf();
			assert.match(list.children[0].props.text, /CII\.xml/);
			await saveDraft();
		} else {
			await saveDraft();
			assert.match(pdf.markup, /normal\.pdf/);
			await queuePdf();
		}
		const bulk = calls.find(({ method }) => method.endsWith(".bulk_create_vorschlaege"));
		assert.deepEqual(JSON.parse(bulk.args.file_urls), ["/private/files/normal.pdf"]);
	});
}
