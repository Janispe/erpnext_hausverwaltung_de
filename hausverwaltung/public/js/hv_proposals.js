frappe.provide("hausverwaltung.hv_proposals");
(() => {
	const labels = { Pending: "Prüfung offen", Approved: "Freigegeben", Succeeded: "Ausgeführt", Stale: "Veraltet", Rejected: "Abgelehnt" };
	const symbols = { Pending: "▶", Approved: "◐", Succeeded: "✓", Stale: "!", Rejected: "/" };
	const bind = ({ id, revision, hash }) => ({ id, revision, hash });
	const renderValue = (cell, value) => {
		const text = value == null ? "" : String(value);
		if (text.includes("\n") || text.length > 80) el("pre", cell, text, "hv-prop-diff-pre");
		else cell.text(text);
	};
	const el = (tag, parent, text, cls) => $(document.createElement(tag)).addClass(cls || "").text(text == null ? "" : text).appendTo(parent);
	const button = (parent, text, fn, primary = false) => el("button", parent, text, "hv-btn" + (primary ? " hv-btn-primary" : "")).attr("type", "button").on("click", fn);
	const tab = (parent, text, fn) => el("button", parent, text, "hv-tab").attr("type", "button").on("click", fn);
	const setActive = (tab, active) => tab.attr("aria-pressed", active).toggleClass("is-active", active);
	const pill = (parent, status) => el("span", parent, `${symbols[status]} ${labels[status]}`, `hv-pill hv-prop-${status}`);
	const person = (p) => p?.label || frappe.user.full_name(p?.name || "") || p?.name || "";
	const time = (value) => value ? frappe.datetime.str_to_user(value) : "";
	const link = (parent, text, doctype, name) => {
		if (!doctype || !name) return el("span", parent, text);
		return el("a", parent, text).attr("href", frappe.utils.get_form_link(doctype, name));
	};
	const bankLink = (parent, text, name, row) => {
		const params = new URLSearchParams({ import: name });
		if (row) params.set("row", row);
		return el("a", parent, text).attr("href", `/app/bankimport_v2?${params}`);
	};
	const money = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
	const confidence = (parent, level) => {
		const line = el("div", parent, "", "hv-prop-confidence");
		el("span", line, "KI", "hv-pill");
		const graph = el("span", line, "", `hv-prop-confidence-bars ${level}`).attr("aria-hidden", "true");
		const active = { niedrig: 1, mittel: 2, hoch: 3 }[level];
		for (let i = 0; i < 3; i++) el("span", graph, "", i < active ? "active" : "");
		el("span", line, level);
	};
	const byColumn = (nodes) => {
		const columns = new Map();
		for (const node of nodes) {
			if (!columns.has(node.column)) columns.set(node.column, []);
			columns.get(node.column).push(node);
		}
		return columns;
	};
	class Inbox {
		constructor(wrapper) {
			this.page = frappe.ui.make_app_page({ parent: wrapper, title: "KI-Vorschläge", single_column: true });
			this.root = el("div", this.page.body, "", "hv hv-prop-root").attr({ tabindex: "0", "aria-label": "KI-Vorschläge" });
			// Administrator erhält in Frappe alle Rollen; er prüft, handelt aber nie als Agent.
			this.reviewer = frappe.user_roles.includes("HV Proposal Reviewer")
				&& (frappe.session.user === "Administrator" || !frappe.user_roles.includes("HV Proposal Agent"));
			this.generation = 0; this.selection = 0; this.filter = "offen"; this.agent = ""; this.kind = "";
			this.root.on("keydown", (e) => this.key(e));
		}
		async call(method, args = {}, context) {
			try { return (await frappe.call({ method: `hausverwaltung.proposals.frappe_service.${method}`, args, type: "POST" })).message; }
			catch (e) {
				if (context && !this.isCurrentPackage(context)) throw e;
				const conflict = e.status === 409 || e.responseJSON?.exc_type === "ConcurrentRevisionRetry";
				frappe.show_alert({ message: conflict ? "Die Daten haben sich gleichzeitig geändert. Bitte erneut versuchen." : "Vorgang nicht verfügbar", indicator: "red" });
				if (conflict) setTimeout(() => {
					if (!context || this.isCurrentPackage(context)) this.route();
				}, 0);
				throw e;
			}
		}
		async route(preferredId) {
			const token = ++this.generation;
			this.displayedNodes = [];
			this.current = null;
			this.package = frappe.get_route()[1] || null;
			this.root.empty(); el("p", this.root, "Pakete werden geladen …");
			try {
				if (!this.package) {
					const rows = []; let start = 0, page;
					do { page = await this.call("list_packages", { start, limit: 100 }); rows.push(...page); start += page.length; } while (page.length === 100);
					if (token !== this.generation) return;
					this.packages = rows; this.renderPackages();
				} else {
					const graph = await this.call("package_graph", { package: this.package });
					if (token !== this.generation) return;
					if (this.graph?.package.package !== this.package) {
						this.mode = graph.edges.length ? "Graph" : "Liste";
						this.expanded = false;
					}
					this.graph = graph;
					const id = preferredId || new URLSearchParams(location.search).get("vorschlag") || this.selected;
					this.selected = graph.nodes.some(n => n.id === id) ? id : graph.nodes[0]?.id;
					if (preferredId && this.selected !== preferredId) {
						frappe.show_alert({ message: "Vorgang nicht verfügbar", indicator: "red" });
					}
					this.renderGraph(); if (this.selected) await this.select(this.selected);
				}
			} catch (_) { if (token === this.generation) this.root.empty().append(el("p", null, "Vorgang nicht verfügbar")); }
		}
		bar(parent, p) {
			const bar = el("div", parent, "", "hv-prop-bar").attr("aria-label", "Stand der Vorschläge");
			for (const status of Object.keys(labels)) if (p.counts[status]) el("span", bar, "", `hv-prop-${status}`).css("flex", p.counts[status]).attr("title", `${p.counts[status]} ${labels[status]}`);
			el("p", parent, Object.entries(p.counts).filter(([, n]) => n).map(([s,n]) => `${n} ${labels[s]}`).join(" · "), "hv-prop-muted");
		}
		renderPackages() {
			this.root.empty(); el("h2", this.root, "KI-Vorschläge");
			el("p", this.root, "Pakete bündeln die Vorschläge eines Agenten. Jede Revision wird einzeln geprüft.", "hv-prop-muted");
			const tabs = el("div", this.root, "", "hv-tabs");
			for (const [status, title] of [["offen","Offen"],["wartet auf Ausführung","Wartet auf Ausführung"],["abgeschlossen","Abgeschlossen"],["","Alle"]]) {
				const filterTab = tab(tabs, `${title} (${this.packages.filter(p => !status || p.status === status).length})`, () => { this.filter = status; this.renderPackages(); });
				setActive(filterTab, this.filter === status);
			}
			const agent = el("select", this.root, "", "hv-field").attr("aria-label", "Agent"); el("option", agent, "Alle Agenten").val("");
			for (const [id,name] of new Map(this.packages.map(p => [p.agent.name, person(p.agent)]))) el("option", agent, name).val(id);
			agent.val(this.agent).on("change", () => { this.agent = agent.val(); this.renderPackages(); });
			const kind = el("select", this.root, "", "hv-field").attr("aria-label", "Art");
			for (const [value, title] of [["", "Alle Arten"], ["booking", "Buchungen"], ["contract", "Verträge"], ["letter", "Briefe"]]) {
				el("option", kind, title).val(value);
			}
			kind.val(this.kind).on("change", () => { this.kind = kind.val(); this.renderPackages(); });
			const rows = this.packages.filter(p => (!this.filter || p.status === this.filter)
				&& (!this.agent || p.agent.name === this.agent) && (!this.kind || p.kind === this.kind));
			if (!rows.length) return void el("p", this.root, "Keine Pakete in diesem Status.");
			const table = el("table", this.root, "", "table").attr("aria-label", "Paketliste"), head = el("tr", el("thead", table));
			for (const title of ["Paket","Agent","Umfang","Stand","Nächster Schritt","Eingang"]) el("th", head, title);
			const body = el("tbody", table);
			for (const p of rows) {
				const row = el("tr", body).attr({ tabindex: "0", "data-package": p.package });
				const open = () => frappe.set_route("hv-proposals", p.package);
				row.on("click", open).on("keydown", e => { if (e.key === "Enter") open(); });
				const title = el("td", row); el("strong", title, p.title);
				el("div", title, p.total === 1 ? "Einzelvorschlag" : p.has_edges ? `Graph · ${p.lanes} ${p.lane_label || "Zeilen"}` : "ohne Abhängigkeiten", "hv-pill");
				if (p.reference) {
					const reference = el("p", title, p.reference.label);
					if (p.kind === "booking") bankLink(reference, " · im Bankimport öffnen", p.reference.name)
						.on("click keydown", e => e.stopPropagation());
				}
				el("td", row, person(p.agent)); el("td", row, `${p.total} Vorschläge`); this.bar(el("td", row), p);
				const action = el("td", row), pending = p.superseded ? 0 : p.counts.Pending + p.counts.Stale;
				if (pending || p.counts.Approved) button(action, pending ? `${pending} prüfen →` : `${p.counts.Approved} ausführen`, e => { e.stopPropagation(); open(); }, true);
				else el("span", action, "Abgeschlossen");
				el("td", row, frappe.datetime.prettyDate(p.created)).attr("title", time(p.created));
			}
		}
		renderGraph() {
			this.root.empty(); const p = this.graph.package;
			button(this.root, "← Alle Pakete", () => frappe.set_route("hv-proposals"));
			el("p", this.root, `Paket · ${p.has_edges ? `Graph mit ${p.lanes} Zeilen` : "ohne Abhängigkeiten"}`, "hv-prop-muted");
			el("h2", this.root, p.title);
			el("p", this.root, `${person(p.agent)} · ${p.reason || "Kein Anlass angegeben"} · ${time(p.created)} · ${p.total} Vorschläge in ${p.lanes} ${p.lane_label || "Zeilen"}`);
			this.bar(this.root, p);
			const controls = el("div", this.root, "", "hv-prop-controls");
			const switcher = el("div", controls, "", "hv-tabs").attr("aria-label", "Ansicht");
			this.viewButtons = new Map();
			for (const mode of (this.graph.nodes.length > 1 ? ["Graph","Liste"] : [])) this.viewButtons.set(mode, tab(switcher, mode, () => { this.mode = mode; this.draw(); }));
			if (p.kind === "booking" && p.reference) {
				bankLink(controls, "Im Bankimport öffnen →", p.reference.name).addClass("hv-btn");
			}
			this.bulkButton = this.reviewer ? button(controls, "Offene freigeben …", () => this.bulkReview()) : null;
			this.executeButton = button(controls, "", () => this.batchExecute(this.displayedBindings("Approved")), true);
			this.feedback = el("div", this.root).attr("role", "status");
			const layout = el("div", this.root, "", "hv-prop-layout");
			this.canvas = el("div", layout, "", "hv-prop-canvas"); this.detail = el("aside", layout, "", "hv-prop-detail").attr("aria-label", "Vorschlagsdetail");
			if (this.graph.nodes.length === 1) this.canvas.hide(), layout.addClass("hv-prop-single");
			this.draw();
		}
		draw() {
			this.canvas.empty();
			for (const [mode, tab] of this.viewButtons) setActive(tab, mode === this.mode);
			const lanes = [...new Map(this.graph.nodes.filter(n => n.lane).map(n => [n.lane.key, n.lane.label]))];
			const shown = this.expanded ? lanes : lanes.slice(0, 5);
			const shownKeys = new Set(shown.map(([key]) => key));
			const isDisplayed = n => this.mode === "Liste" || !n.lane || shownKeys.has(n.lane.key);
			this.displayedNodes = this.graph.nodes.filter(isDisplayed);
			this.bulkButton?.prop("disabled", !this.displayedBindings("Pending").length);
			const approvedCount = this.displayedBindings("Approved").length;
			this.executeButton.text(`Freigegebene ausführen (${approvedCount})`).prop("disabled", !approvedCount);
			if (this.mode === "Liste") {
				const table = el("table", this.canvas, "", "table").attr("aria-label", "Vorschlagsliste"), header = el("tr", el("thead", table)), body = el("tbody", table);
				for (const t of ["Zeile","Schritt","Änderung","Status"]) el("th", header, t);
				for (const n of this.displayedNodes) { const row = el("tr", body).attr({ tabindex:"0", "aria-selected": this.selected === n.id }); el("td", row, n.lane?.label || "Wurzel"); el("td", row, `${n.title} · ${n.id}`); el("td", row, n.summary); pill(el("td", row), n.status); row.on("click", () => this.select(n.id)).on("keydown", e => { if (e.key === "Enter") this.select(n.id); }); }
				return;
			}
			el("p", this.canvas, "Durchgezogen: Vorgänger ausgeführt · Gestrichelt: wartet auf Ausführung", "hv-prop-muted");
			const scroll = el("div", this.canvas, "", "hv-prop-scroll"), board = el("div", scroll, "", "hv-prop-board");
			const { positions, laneTops } = this.positionGraph(shown);
			const width = Math.max(200,...[...positions.values()].map(p => p.x+200)), height = Math.max(150,...[...positions.values()].map(p => p.y+100));
			board.css({ width, height });
			const svg = document.createElementNS("http://www.w3.org/2000/svg","svg"); $(svg).attr({ width, height, "aria-hidden":"true" }).appendTo(board);
			for (const edge of this.graph.edges) {
				const a = positions.get(edge.from), b = positions.get(edge.to); if (!a || !b) continue;
				const path = document.createElementNS(svg.namespaceURI,"path"), mid = a.x+208;
				$(path).attr({ d:`M${a.x+200},${a.y+42} H${mid} V${b.y+42} H${b.x}`, class: edge.satisfied ? "hv-prop-edge" : "hv-prop-edge hv-prop-edge-pending" }).appendTo(svg);
			}
			for (const [key, label] of shown) el("span", board, label, "hv-prop-lane").css({ left:216, top:laneTops.get(key) });
			for (const n of this.displayedNodes) {
				const pos = positions.get(n.id), node = button(board, "", () => this.select(n.id)).addClass(`hv-prop-node hv-prop-${n.status}`).css({ left:pos.x,top:pos.y }).attr({ "aria-label": `${n.id} ${n.title}, ${labels[n.status]}`, "aria-pressed": n.id === this.selected, "data-node":n.id });
				const head = el("span", node, "", "hv-prop-node-head");
				el("span", head, symbols[n.status], "hv-prop-node-glyph").attr("aria-hidden", "true");
				const title = el("span", head, "", "hv-prop-node-caption");
				el("strong",title,n.title,"hv-prop-node-title"); el("small",title,n.id); el("span",node,n.summary,"hv-prop-summary"); el("small",node,labels[n.status]);
			}
			if (lanes.length > shown.length) {
				const hidden = this.graph.nodes.filter(n => !isDisplayed(n));
				const counts = Object.keys(labels).map(s => `${hidden.filter(n => n.status === s).length} ${labels[s]}`);
				button(this.canvas, `${lanes.length - shown.length} weitere ${this.graph.package.lane_label || "Zeilen"} · ${counts.join(" · ")}`, () => {
					this.expanded = true;
					this.draw();
				});
			}
		}
		positionGraph(shown) {
			const positions = new Map();
			const laneTops = new Map();
			const laneColumns = new Set();
			const groups = new Map(shown.map(([key]) => [key, []]));
			const unlaned = [];
			for (const node of this.displayedNodes) {
				(node.lane ? groups.get(node.lane.key) : unlaned).push(node);
			}
			const place = (column, nodes, row) => {
				nodes.forEach((node, index) => positions.set(node.id, { x: column * 216, y: 32 + (row + index) * 128 }));
			};
			let row = 0;
			for (const [key, nodes] of groups) {
				laneTops.set(key, row * 128);
				let slots = 1;
				for (const [column, stack] of byColumn(nodes)) {
					laneColumns.add(column);
					place(column, stack, row);
					slots = Math.max(slots, stack.length);
				}
				row += slots;
			}
			for (const [column, stack] of byColumn(unlaned)) {
				// Keep roots centered unless that column already contains lane nodes.
				place(column, stack, laneColumns.has(column) ? row : Math.max(0, (row - stack.length) / 2));
			}
			return { positions, laneTops };
		}
		displayedBindings(status) {
			return this.displayedNodes.filter(node => node.status === status).map(bind);
		}
		async select(id) {
			if (!this.graph.nodes.some(node => node.id === id)) return this.route(id);
			if (this.mode === "Graph" && !this.displayedNodes.some(node => node.id === id)) this.expanded = true;
			const focused = this.root[0].contains(document.activeElement);
			this.current = null; this.selected = id; const token = ++this.selection, generation = this.generation;
			this.draw(); this.detail.empty(); if (focused) this.root.trigger("focus");
			try {
				const p = await this.call("view", { proposal_id:id }), events = await this.call("audit", { proposal_id:id });
				if (token !== this.selection || generation !== this.generation) return;
				this.current = p; this.renderDetail(p,events);
			} catch (_) { /* The normal API error is already presented. */ }
		}
		renderDetail(p, events) {
			this.detail.empty(); const box = this.detail, node = this.graph.nodes.find(n => n.id === p.id);
			el("small",box,p.target.doctype); pill(box,p.status); el("h3",box,p.title); if (p.target.row) bankLink(box, p.target.label, p.target.name, p.target.row);
			else link(box,p.target.label,p.target.doctype,p.target.name);
			const siblings = this.graph.nodes.filter(n => n.lane?.key === node.lane?.key);
			el("p",box,`${p.id} · Revision ${p.revision} · ${p.hash.slice(0,10)} · Zeile ${p.lane?.label || "Wurzel"} · Schritt ${siblings.findIndex(n=>n.id===p.id)+1} von ${siblings.length}`,"hv-prop-muted");
			if (p.status === "Approved" || p.status === "Rejected") el("p",box,`${person(p.decision_by)} · ${time(p.decision_at)} · gilt nur für Revision ${p.revision}${p.reject_reason ? " · "+p.reject_reason : ""}`);
			if (p.status === "Stale") { const causes = { baseline_changed:"Das Zieldokument hat sich geändert.",dependency_revised:"Ein Vorgänger wurde überarbeitet.",dependency_rejected:"Ein Vorgänger wurde abgelehnt.",dependency_stale:"Ein Vorgänger ist veraltet.",superseded:"Ein neuer Lauf hat das Vorschlagspaket ersetzt." }; el("p",box,causes[p.stale_cause?.cause] || "Die Vorschau ist veraltet."); }
			if (p.status === "Succeeded" && p.result) { const event = events.find(e => e.kind === "Succeeded"); el("p",box,`Ausgeführt ${time(event?.creation)}`); if (p.result.doctype && p.result.id) link(box,"Dokument öffnen →",p.result.doctype,p.result.id); }
			el("h4",box,"Änderung"); const table = el("table",box,"","table"), header = el("tr",table); for (const t of ["Feld","Bisher","Neu"]) el("th",header,t);
			for (const c of p.changes) { const row = el("tr",table); el("td",row,c.label); renderValue(el("td",row), c.before); const after = el("td",row); if (c.kind === "text" && c.segments) for (const seg of c.segments) el(seg.op === "del" ? "del" : seg.op === "ins" ? "ins" : "span",after,seg.text); else renderValue(after, c.after); }
			if (p.postings?.length) {
				el("h4", box, "Buchung (Vorschau)");
				const postings = el("table", box, "", "table").attr("aria-label", "Buchung (Vorschau)");
				const header = el("tr", el("thead", postings));
				for (const label of ["Konto", "Soll", "Haben"]) el("th", header, label);
				const body = el("tbody", postings);
				for (const entry of p.postings) {
					const row = el("tr", body);
					el("td", row, entry.label);
					el("td", row, entry.debit ? money.format(entry.debit) : "–");
					el("td", row, entry.credit ? money.format(entry.credit) : "–");
				}
			}
			el("h4",box,"Begründung des Agenten");
			if (p.confidence) confidence(box, p.confidence.level);
			el("em",box,p.rationale || "Keine Begründung angegeben."); for (const source of p.sources || []) link(el("p",box),source.label,source.doctype,source.name);
			el("h4", box, "Im Graph");
			for (const [title, items] of [["Vorgänger", p.predecessors], ["Nachfolger", p.successors]]) {
				const group = el("div", box, "", "hv-prop-neighbors").attr({ role: "group", "aria-label": title });
				el("small", group, title);
				if (!items.length) el("span", group, "keine");
				for (const n of items) button(group, `${n.title} · ${labels[n.status]}`, () => this.select(n.id));
			}
			if (p.status === "Approved" && !node.executable) el("p",box,"Ausführen erst, wenn alle Vorgänger ausgeführt sind. Freigeben geht schon jetzt.");
			el("h4",box,"Beim Ausführen"); const effects = el("ul",box).attr("aria-label", "Auswirkungen"); for (const effect of p.effects) el("li",effects,this.translateEffect(effect));
			if (p.target.row && ["Pending", "Approved"].includes(p.status)) {
				el("p", box, "Ausgeführt wird über dieselbe Logik wie ‚Übernehmen & buchen‘ im Bankimport.");
			}
			const actions = el("div",box,"","hv-prop-controls");
			if (p.status === "Pending" && this.reviewer) { button(actions,`Revision ${p.revision} freigeben`,()=>this.review(p,true),true); button(actions,"Ablehnen …",()=>this.reasonDialog(p,false)).addClass("hv-btn-danger"); el("p",box,"Ablehnen macht alle Nachfolger veraltet."); }
			else if (p.status === "Stale" && this.reviewer && !this.graph.package.superseded) button(actions,"Neue Revision anfordern",()=>this.reasonDialog(p,true),true);
			else if (!this.reviewer && ["Pending", "Stale"].includes(p.status)) el("p",box,"Nur Prüfer können freigeben.");
			if (p.status === "Approved") {
				if (this.reviewer || p.target?.doctype === "HV Synthetic Note" || p.target?.row) { button(actions,"Ausführen",()=>this.batchExecute([bind(p)]),true).prop("disabled",!node.executable); el("p",box,"Speichert über die normale Frappe-Validierung."); }
				else el("p",box,"Nur Prüfer können freigegebene Dokumentvorschläge ausführen.");
			}
			el("h4",box,"Verlauf"); const history = el("ol",box).attr("aria-label","Verlauf");
			const titles = { Created:"Vorschlag eingereicht",Revised:"Neue Revision",Approved:"Freigegeben",Rejected:"Abgelehnt",Stale:"Veraltet",Succeeded:"Ausgeführt",RevisionRequested:"Nachbesserung angefordert",ResultReused:"Ergebnis erneut abgerufen",ExecutionFailed:"Buchung fehlgeschlagen" };
			for (const e of events) { const d = (e.detail ? JSON.parse(e.detail) : null) || {}; el("li",history,`${titles[e.kind] || "Ereignis"}${e.kind === "Approved" && d.surface === "bankimport" ? " (im Bankimport)" : ""} · ${e.actor_name || frappe.user.full_name(e.actor)} · ${time(e.creation)}${d.note || d.reason ? " · "+(d.note || d.reason) : ""}`); }
			const technical = el("details",box); el("summary",technical,"Technische Details"); el("p",technical,p.hash); for (const limit of p.limits) el("p",technical,this.translateEffect(limit));
		}
		translateEffect(text) {
			return ({
				bankimport_party: "Die Partei wird zugeordnet und die Banktransaktion angelegt.",
				bankimport_invoice: "Die Zahlung wird gebucht und den ausgewählten Rechnungen zugeordnet.",
				bankimport_split: "Die Zahlung wird gebucht und auf die ausgewählten Positionen verteilt.",
				bankimport_abschlag: "Die Anzahlung wird gebucht und dem Abschlagsplan zugeordnet.",
				bankimport_kredit: "Die Kreditrate wird gebucht und mit dem Bankumsatz verknüpft.",
				bankimport_payment: "Die Zahlung wird als Vorauszahlung gebucht.",
				bankimport_transfer: "Die interne Umbuchung wird gebucht.",
				bankimport_journal: "Der Buchungssatz wird als Journalbuchung gebucht.",
				"Normal save updates modified/modified_by and generation":"Normales Speichern aktualisiert Änderungszeit, Bearbeiter und Generation.","Synthetic local label only":"Nur die Bezeichnung einer synthetischen Notiz.","No financial, mail, jobs or external actions":"Keine Buchungen, E-Mails, Jobs oder externen Aktionen.","Normal validation/hooks run only at execute; unknown hook effects are not simulated":"Validierungen und Hooks laufen erst beim Ausführen; unbekannte Hookfolgen werden nicht simuliert." })[text] || text;
		}
		reasonDialog(p, request) {
			const dialog = new frappe.ui.Dialog({ title:request ? "Neue Revision anfordern" : "Vorschlag ablehnen", fields:[{ fieldname:"reason",label:request ? "Notiz" : "Ablehnungsgrund",fieldtype:"Small Text",reqd:1 }],primary_action_label:request ? "Anfordern" : "Ablehnung bestätigen",primary_action:async values => { dialog.hide(); try { if (request) await this.call("request_revision",{binding:bind(p),note:values.reason}); else await this.call("review",{binding:bind(p),approve:false,reason:values.reason}); await this.route(); } catch (_) {} } }); dialog.show();
		}
		async review(p, approve) { try { await this.call("review",{binding:bind(p),approve}); await this.route(); } catch (_) {} }
		bulkReview() {
			const refs = this.displayedBindings("Pending");
			if (!refs.length) return;
			const context = this.packageContext();
			const dialog = new frappe.ui.Dialog({
				title: `${refs.length} offene Vorschläge freigeben`,
				fields: [{fieldtype:"HTML",fieldname:"notice"}],
				primary_action_label: "Freigaben bestätigen",
				primary_action: async () => {
					dialog.hide();
					if (!this.isCurrentPackage(context)) return;
					try {
						const result = await this.call("review_many", {bindings:refs}, context);
						await this.showBatchResult(context, result, true);
					} catch (_) { /* The normal API error is already presented. */ }
				}
			});
			dialog.fields_dict.notice.$wrapper.text("Jede Freigabe wird einzeln für ihre Revision und ihren Hash protokolliert. Freigegeben werden nur sichtbare Vorschläge. Veraltete und abgelehnte Vorschläge bleiben unverändert. Ausgeführt wird erst mit ‚Freigegebene ausführen‘."); dialog.show();
		}
		async batchExecute(refs) {
			if (!refs.length) return;
			const context = this.packageContext();
			try {
				const result = await this.call("execute_ready", {package:context.package, bindings:refs}, context);
				await this.showBatchResult(context, result);
			} catch (_) { /* The normal API error is already presented. */ }
		}
		packageContext() {
			return {package:this.package, generation:this.generation};
		}
		isCurrentPackage(context) {
			const [page, packageId] = frappe.get_route();
			return page === "hv-proposals" && packageId === context.package
				&& this.package === context.package && this.generation === context.generation;
		}
		async showBatchResult(context, rows, reviewing = false) {
			if (!this.isCurrentPackage(context)) return;
			const refresh = this.route();
			const refreshedContext = this.packageContext();
			await refresh;
			if (!this.isCurrentPackage(refreshedContext) || !this.feedback?.[0]?.isConnected) return;
			this.results(rows, reviewing);
			if (!reviewing) {
				const failed = rows.find(row => !row.ok && !row.skipped_reason);
				if (failed) await this.select(failed.id);
			}
		}
		results(rows, review = false) {
			this.feedback.empty(); const ok = rows.filter(r=>r.ok).length, waiting = rows.filter(r=>r.skipped_reason).length;
			el("p",this.feedback,review ? `${ok} einzeln freigegeben` : `${ok} in Reihenfolge ausgeführt · ${waiting} warten auf Vorgänger`);
			for (const row of rows.filter(r=>!r.ok)) el("p",this.feedback,`${row.id}: ${row.skipped_reason ? "Wartet auf Vorgänger" : row.status === "Stale" ? "Veraltet – neue Revision erforderlich" : "Vorgang nicht verfügbar"}`);
			frappe.show_alert({message:`${ok} Vorschläge verarbeitet`,indicator:"green"});
		}
		key(e) {
			if (e.ctrlKey || e.altKey || e.metaKey || $(e.target).is("input,textarea,select,[contenteditable=true]") || $(".modal:visible").length || !this.displayedNodes?.length || !this.package) return;
			const index = this.displayedNodes.findIndex(n=>n.id===this.selected);
			if (["j","k"].includes(e.key.toLowerCase())) { e.preventDefault(); this.select(this.displayedNodes[Math.max(0,Math.min(this.displayedNodes.length-1,index+(e.key.toLowerCase()==="j"?1:-1)))].id); }
			else if (this.current?.id === this.selected) { const p=this.current; if (e.key.toLowerCase()==="a" && this.reviewer && p.status==="Pending") this.review(p,true); if(e.key.toLowerCase()==="r" && this.reviewer && p.status==="Pending") this.reasonDialog(p,false); if(e.key.toLowerCase()==="e" && p.status==="Approved" && this.graph.nodes.find(n=>n.id===p.id).executable) this.batchExecute([bind(p)]); }
		}
	}
	hausverwaltung.hv_proposals.Inbox = Inbox;
})();
