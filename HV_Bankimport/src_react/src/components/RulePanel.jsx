import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { Icon, Spinner } from "../helpers.jsx";

const GROUP_ORDER = ["party", "booking"];
const DOCTYPE_KIND = {
	"Bankimport Party Regel": "party",
	"Bankimport Buchungsregel": "booking",
};
const KIND_DOCTYPE = {
	party: "Bankimport Party Regel",
	booking: "Bankimport Buchungsregel",
};
const FIELD_LABELS = {
	iban: "IBAN",
	auftraggeber: "Auftraggeber",
	zweck: "Zweck",
	betrag: "Betrag",
	richtung: "Richtung",
	party_type: "Party Type",
	party: "Party",
};
const FIELDS = ["iban", "auftraggeber", "zweck", "betrag", "richtung", "party_type", "party"];
const OPS = ["enthält", "beginnt mit", "=", "!=", ">", "<", ">=", "<=", "ist leer", "ist nicht leer"];
const FILTER_OPS = [...OPS];
const PARTY_TYPES = [
	["Customer", "Mieter / Kunde"],
	["Supplier", "Lieferant"],
	["Eigentuemer", "Eigentümer"],
];
function parseParams(rule) {
	if (rule?.parameters && typeof rule.parameters === "object") return rule.parameters;
	if (!rule?.parametersJson) return {};
	try {
		const parsed = JSON.parse(rule.parametersJson);
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

function titleOf(rule) {
	return rule?.title || rule?.description?.split(/\n/)[0] || rule?.ruleKey || rule?.name || "Regel";
}

function isDoneRow(row) {
	return row?.phase >= 4 || ["done", "existing", "skipped"].includes(row?.rowStatus);
}

function fieldValue(field, row) {
	if (field === "iban") return row.iban || "";
	if (field === "auftraggeber") return row.auftraggeber || "";
	if (field === "zweck") return row.verwendungszweck || "";
	if (field === "betrag") return Math.abs(Number(row.betrag) || 0);
	if (field === "richtung") return row.richtung || ((Number(row.betrag) || 0) < 0 ? "Ausgang" : "Eingang");
	if (field === "party_type") return row.partyTyp || row.party_type || "";
	if (field === "party") return row.party || "";
	return "";
}

function normalizeSource(condition) {
	return condition?.source === "doctype" ? "doctype" : "row";
}

function parseNumber(value) {
	const raw = String(value || "0").trim();
	const normalized = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
	return Number.parseFloat(normalized) || 0;
}

function conditionMatches(condition, row) {
	if (normalizeSource(condition) === "doctype") return false;
	const lhs = fieldValue(condition.field, row);
	const rhs = condition.value ?? "";
	if (condition.op === "ist leer") return lhs === null || lhs === undefined || lhs === "";
	if (condition.op === "ist nicht leer") return !(lhs === null || lhs === undefined || lhs === "");
	if (condition.field === "betrag") {
		const a = Number(lhs) || 0;
		const b = parseNumber(rhs);
		if (condition.op === "=") return a === b;
		if (condition.op === "!=") return a !== b;
		if (condition.op === ">") return a > b;
		if (condition.op === "<") return a < b;
		if (condition.op === ">=") return a >= b;
		if (condition.op === "<=") return a <= b;
		return false;
	}
	const a = String(lhs).toLowerCase();
	const b = String(rhs).toLowerCase();
	if (condition.op === "enthält") return a.includes(b);
	if (condition.op === "beginnt mit") return a.startsWith(b);
	if (condition.op === "=") return a === b;
	if (condition.op === "!=") return a !== b;
	return false;
}

function builderMatches(builder, row) {
	const conditions = builder?.conditions || [];
	if (!conditions.length) return false;
	const hits = conditions.map((condition) => conditionMatches(condition, row));
	return builder.connector === "oder" ? hits.some(Boolean) : hits.every(Boolean);
}

function builderNeedsServer(builder) {
	return (builder?.conditions || []).some((condition) => normalizeSource(condition) === "doctype");
}

function validateBuilder(builder) {
	const conditions = builder?.conditions || [];
	if (!conditions.length) return "Mindestens eine Bedingung ist erforderlich.";
	for (const condition of conditions) {
		if (normalizeSource(condition) === "doctype") {
			if (!condition.doctype) return "DocType-Bedingungen benötigen einen DocType.";
			if (!Array.isArray(condition.filters) || !condition.filters.length) return "DocType-Bedingungen benötigen mindestens einen Filter.";
			for (const filter of condition.filters) {
				if (!filter.field) return "Jeder DocType-Filter benötigt ein Feld.";
				if (!FILTER_OPS.includes(filter.op)) return "Unbekannter DocType-Filteroperator.";
				if (!["ist leer", "ist nicht leer"].includes(filter.op) && filter.valueSource !== "row" && (filter.value === undefined || filter.value === "")) return "DocType-Filter benötigen einen Vergleichswert.";
				if (filter.valueSource === "row" && !filter.rowField) return "DocType-Filter mit Bankzeilenwert benötigen ein Bankzeilenfeld.";
			}
			if ((condition.matchMode || "field") !== "exists") {
				if (!condition.field) return "Der DocType-Feldvergleich benötigt ein Feld.";
				if (!OPS.includes(condition.op)) return "Unbekannter Operator.";
				if (!["ist leer", "ist nicht leer"].includes(condition.op) && condition.valueSource !== "row" && (condition.value === undefined || condition.value === "")) return "Der DocType-Feldvergleich benötigt einen Wert.";
				if (condition.valueSource === "row" && !condition.rowField) return "Der DocType-Feldvergleich benötigt ein Bankzeilenfeld.";
			}
			continue;
		}
		if (!FIELDS.includes(condition.field)) return "Unbekanntes Feld.";
		if (!OPS.includes(condition.op)) return "Unbekannter Operator.";
		if (!["ist leer", "ist nicht leer"].includes(condition.op) && (condition.value === undefined || condition.value === "")) return "Jede Bedingung benötigt einen Wert.";
	}
	return "";
}

function exprText(builder) {
	const connector = ` ${builder?.connector || "und"} `;
	return (builder?.conditions || [])
		.map((condition) => {
			if (normalizeSource(condition) === "doctype") {
				const filters = (condition.filters || []).map((filter) => `${filter.field} ${filter.op} ${filter.valueSource === "row" ? `Bankzeile.${FIELD_LABELS[filter.rowField] || filter.rowField}` : `"${filter.value || ""}"`}`).join(", ");
				const target = (condition.matchMode || "field") === "exists" ? "Treffer existiert" : `${condition.field} ${condition.op} ${condition.valueSource === "row" ? `Bankzeile.${FIELD_LABELS[condition.rowField] || condition.rowField}` : `"${condition.value || ""}"`}`;
				return `${condition.doctype}(${filters}) · ${target}`;
			}
			return `${FIELD_LABELS[condition.field] || condition.field} ${condition.op} ${["ist leer", "ist nicht leer"].includes(condition.op) ? "" : `"${condition.value || ""}"`}`.trim();
		})
		.join(connector);
}

function actionText(action) {
	if (!action) return "";
	if (["party", "partei"].includes(action.type)) return `${action.party_type || action.partyType || "Party"} · ${action.party || ""}`;
	if (["party_from_row", "partei_aus_zeile"].includes(action.type)) return "Partei aus Bankzeile";
	if (["party_from_doctype", "partei_aus_doctype"].includes(action.type)) return `${action.doctype || "DocType"} · ${action.partyTypeField || "party_type"} / ${action.partyField || "party"}`;
	if (["builtin", "system"].includes(action.type)) return action.ruleKey || action.rule_key || "Backend-Aktion";
	if (["buchung", "booking"].includes(action.type)) return `${action.account || action.konto || ""}${action.cost_center || action.kostenstelle ? ` · ${action.cost_center || action.kostenstelle}` : ""}`;
	return "";
}

function scopeLabel(entry) {
	const mode = entry.mode || "Sperren";
	const type = entry.scopeType || "IBAN";
	if (type === "IBAN") return `${mode}: ${entry.iban || "IBAN"}`;
	if (type === "Party Type") return `${mode}: ${entry.partyType || "Party Type"}`;
	return `${mode}: ${[entry.partyType, entry.party].filter(Boolean).join(" / ") || "Party"}`;
}

function InkToggle({ checked, onChange, disabled }) {
	return (
		<button
			type="button"
			className={`rp-status ${checked ? "on" : "off"}`}
			role="switch"
			aria-checked={checked}
			disabled={disabled}
			onClick={() => onChange(!checked)}
			title={checked ? "Regel deaktivieren" : "Regel aktivieren"}
		>
			<span className="rp-status-track"><span className="rp-status-knob" /></span>
		</button>
	);
}

function RuleCard({ rule, rows, index, total, onEdit, onToggle, onReorder, onDelete, busy }) {
	const params = parseParams(rule);
	const builder = rule.builder || params.builder;
	const action = rule.action || params.action;
	const isBuilder = Boolean(rule.isBuilderRule || builder);
	const needsServerPreview = isBuilder && builderNeedsServer(builder);
	const hits = isBuilder && rows?.length && !needsServerPreview
		? rows.filter((row) => !isDoneRow(row) && builderMatches(builder, row)).length
		: null;
	const disabled = !rule.enabled;
	const scope = rule.scope || [];

	return (
		<div className={`rule-card ${disabled ? "inactive" : ""}`}>
			<div className="rc-head">
				<div className="rc-prio-col">
					<button className="rc-prio-btn" disabled={index === 0 || busy} onClick={() => onReorder(rule, -1)} title="Priorität erhöhen">▲</button>
					<span className="rc-prio">{rule.priority ?? "—"}</span>
					<button className="rc-prio-btn" disabled={index === total - 1 || busy} onClick={() => onReorder(rule, 1)} title="Priorität senken">▼</button>
				</div>
				<div className="rc-titlewrap">
					<div className="rc-title">{titleOf(rule)}</div>
					<div className="rc-key mono">{rule.ruleKey || rule.name}</div>
				</div>
				<InkToggle checked={Boolean(rule.enabled)} disabled={busy} onChange={(next) => onToggle(rule, next)} />
			</div>

			{rule.description && <div className="rc-desc">{rule.description}</div>}

			{isBuilder && (
				<div className="rc-sig mono">
					<span className="fn-g">ƒ</span> wenn {exprText(builder)} <span className="fn-arrow">→</span> <span className="fn-out">{actionText(action)}</span>
				</div>
			)}
			<div className="rc-badges">
				{rule.stopOnMatch && <span className="rc-badge">Stoppt bei Treffer</span>}
				{rule.autoApply && <span className="rc-badge">Automatisch</span>}
				{rule.requiresReview && <span className="rc-badge warn">Prüfung</span>}
				{isBuilder
					? <span className="rc-badge soft">Builder</span>
					: <span className="rc-badge soft">DB-Code · {rule.ruleCodeLines || 0}</span>}
				{scope.length > 0 && <span className="rc-badge accent">Scope · {scope.length}</span>}
			</div>

			<div className="rc-foot">
				<div className="rc-foot-left">
					{isBuilder
						? needsServerPreview
							? <span className="rp-hits">Server-Vorschau</span>
							: hits > 0 ? <span className="rp-hits has">↻ {hits} {hits === 1 ? "Zeile" : "Zeilen"} im Auszug</span> : <span className="rp-hits">keine Treffer</span>
						: <span className="rc-foot-note">Backend-Regel</span>}
				</div>
				<div className="rc-actions">
					<button className="btn subtle sm" onClick={() => onEdit(rule)}><Icon name="settings" size={13} /> Bearbeiten</button>
					<button className="icon-btn danger" onClick={() => onDelete(rule)} title="Löschen" aria-label="Löschen"><Icon name="trash" size={13} /></button>
				</div>
			</div>
		</div>
	);
}

function RuleColumn({ group, rows, onNew, onEdit, onToggle, onReorder, onDelete, busy }) {
	const items = [...(group?.items || [])].sort((a, b) => (a.priority || 0) - (b.priority || 0));
	const active = items.filter((rule) => rule.enabled).length;
	return (
		<section className="rule-col">
			<div className="rule-col-head">
				<div>
					<h3 className="rule-col-title">{group?.label || "Regeln"}</h3>
					<div className="rule-col-count">{active} aktiv · {items.length - active} aus</div>
				</div>
				<button className="btn primary sm" onClick={() => onNew(group)}><Icon name="plus" size={13} /> Neu</button>
			</div>
			<div className="rule-col-list">
				{items.length === 0 ? <div className="rule-col-empty">Keine Regeln in dieser Spalte.</div> : items.map((rule, index) => (
					<RuleCard
						key={`${rule.doctype}:${rule.name}`}
						rule={rule}
						rows={rows}
						index={index}
						total={items.length}
						onEdit={onEdit}
						onToggle={onToggle}
						onReorder={onReorder}
						onDelete={onDelete}
						busy={busy}
					/>
				))}
			</div>
		</section>
	);
}

function GraphColumn({ group }) {
	const items = [...(group?.items || [])].sort((a, b) => (a.priority || 0) - (b.priority || 0));
	return (
		<section className="graph-col">
			<h3 className="rule-col-title">{group?.label || "Regeln"}</h3>
			<div className="graph-flow">
				<div className="graph-cap start">BANK-ZEILE</div>
				{items.map((rule) => (
					<React.Fragment key={`${rule.doctype}:${rule.name}`}>
						<div className="graph-arrow" aria-hidden="true">↓</div>
						<div className={`graph-node ${rule.enabled ? "" : "inactive"} ${rule.requiresReview ? "review" : ""}`}>
							<span className="gn-prio">{rule.priority ?? "—"}</span>
							<div className="gn-body">
								<div className="gn-title">{titleOf(rule)}</div>
								<div className="gn-key mono">{rule.ruleKey || rule.name}</div>
							</div>
							{rule.enabled
								? rule.stopOnMatch ? <span className="gn-flag stop">Treffer → fertig</span> : <span className="gn-flag pass">läuft weiter</span>
								: <span className="gn-flag off">aus</span>}
						</div>
					</React.Fragment>
				))}
				<div className="graph-arrow" aria-hidden="true">↓</div>
				<div className="graph-cap end">offen / zur Prüfung</div>
			</div>
		</section>
	);
}

function defaultCondition(source = "row") {
	if (source === "doctype") {
		return {
			source: "doctype",
			doctype: "Bank Account",
			filters: [defaultDoctypeFilter()],
			matchMode: "exists",
			field: "",
			op: "=",
			valueSource: "literal",
			value: "",
		};
	}
	return { source: "row", field: "auftraggeber", op: "enthält", value: "" };
}

function defaultDoctypeFilter() {
	return { field: "iban", op: "=", valueSource: "row", rowField: "iban", value: "" };
}

function makeInitialEditorState(state) {
	const rule = state.rule || {};
	const kind = DOCTYPE_KIND[state.doctype || rule.doctype] || state.kind || "booking";
	const params = parseParams(rule);
	const builder = params.builder || { connector: "und", conditions: [defaultCondition()] };
	const action = params.action || {
		type: kind === "party" ? "party" : "buchung",
		party_type: "Customer",
		party: "",
		account: "",
		cost_center: "Allgemein",
	};
	return {
		name: rule.name || "",
		doctype: state.doctype || rule.doctype || KIND_DOCTYPE[kind],
		kind,
		title: titleOf(rule) === "Regel" ? "" : titleOf(rule),
		ruleKey: rule.ruleKey || (kind === "party" ? "party.neue_regel" : "booking.neue_regel"),
		description: rule.description || "",
		priority: rule.priority ?? 100,
		enabled: rule.enabled !== false,
		stopOnMatch: rule.stopOnMatch !== false,
		autoApply: rule.autoApply !== false,
		requiresReview: Boolean(rule.requiresReview),
		builder: {
			connector: builder.connector || "und",
			conditions: builder.conditions?.length ? builder.conditions : [defaultCondition()],
		},
		action,
		scope: (rule.scope || []).map((entry) => ({ enabled: entry.enabled !== false, ...entry })),
		mode: params.ui?.mode || "einfach",
		isBuilderRule: Boolean(rule.isBuilderRule || params.builder),
		forceBuilder: false,
		ruleCodeLines: rule.ruleCodeLines || 0,
	};
}

function ValueSourceInput({ valueSource = "literal", value = "", rowField = "iban", op, onChange, placeholder = "Wert" }) {
	if (["ist leer", "ist nicht leer"].includes(op)) return <div className="value-empty-note">kein Wert nötig</div>;
	return (
		<div className="value-source">
			<select className="text-input compact" value={valueSource || "literal"} onChange={(e) => onChange({ valueSource: e.target.value })}>
				<option value="literal">Wert</option>
				<option value="row">Bankzeile</option>
			</select>
			{valueSource === "row" ? (
				<select className="text-input" value={rowField || "iban"} onChange={(e) => onChange({ rowField: e.target.value })}>
					{FIELDS.map((field) => <option value={field} key={field}>{FIELD_LABELS[field]}</option>)}
				</select>
			) : (
				<input className="text-input" value={value || ""} onChange={(e) => onChange({ value: e.target.value })} placeholder={placeholder} />
			)}
		</div>
	);
}

function DoctypeConditionEditor({ condition, index, doctypes, setCondition }) {
	const [fields, setFields] = useState([]);
	const doctype = condition.doctype || "";
	useEffect(() => {
		let alive = true;
		if (!doctype) {
			setFields([]);
			return () => { alive = false; };
		}
		api.getRuleDoctypeFields(doctype)
			.then((result) => { if (alive) setFields(result.items || []); })
			.catch(() => { if (alive) setFields([]); });
		return () => { alive = false; };
	}, [doctype]);

	const fieldOptions = fields.length ? fields : [
		{ value: "name", label: "Name" },
		{ value: "iban", label: "IBAN" },
		{ value: "party_type", label: "Party Type" },
		{ value: "party", label: "Party" },
	];
	const filters = condition.filters?.length ? condition.filters : [defaultDoctypeFilter()];
	const patchFilter = (filterIndex, next) => setCondition(index, {
		filters: filters.map((filter, idx) => idx === filterIndex ? { ...filter, ...next } : filter),
	});
	const addFilter = () => setCondition(index, { filters: [...filters, defaultDoctypeFilter()] });
	const removeFilter = (filterIndex) => setCondition(index, { filters: filters.filter((_, idx) => idx !== filterIndex) });

	return (
		<div className="doctype-condition">
			<div className="doc-row">
				<label>
					<span className="field-label">DocType</span>
					<input className="text-input" list="rule-doctype-options" value={doctype} onChange={(e) => setCondition(index, { doctype: e.target.value })} placeholder="Bank Account" />
				</label>
				<datalist id="rule-doctype-options">
					{doctypes.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
				</datalist>
				<label>
					<span className="field-label">Prüfung</span>
					<select className="text-input" value={condition.matchMode || "exists"} onChange={(e) => setCondition(index, { matchMode: e.target.value })}>
						<option value="exists">Treffer existiert</option>
						<option value="field">Feld vergleichen</option>
					</select>
				</label>
			</div>
			<div className="filter-stack">
				<div className="field-label">Filter</div>
				{filters.map((filter, filterIndex) => (
					<div className="filter-row" key={filterIndex}>
						<select className="text-input" value={filter.field || ""} onChange={(e) => patchFilter(filterIndex, { field: e.target.value })}>
							<option value="">Feld</option>
							{fieldOptions.map((field) => <option value={field.value} key={field.value}>{field.label || field.value}</option>)}
						</select>
						<select className="text-input compact" value={filter.op || "="} onChange={(e) => patchFilter(filterIndex, { op: e.target.value })}>
							{FILTER_OPS.map((op) => <option value={op} key={op}>{op}</option>)}
						</select>
						<ValueSourceInput
							valueSource={filter.valueSource || "literal"}
							rowField={filter.rowField || "iban"}
							value={filter.value || ""}
							op={filter.op}
							onChange={(next) => patchFilter(filterIndex, next)}
						/>
						<button type="button" className="icon-btn" disabled={filters.length <= 1} onClick={() => removeFilter(filterIndex)}><Icon name="x" size={13} /></button>
					</div>
				))}
				<button type="button" className="btn subtle sm" onClick={addFilter}><Icon name="plus" size={13} /> Filter</button>
			</div>
			{(condition.matchMode || "exists") === "field" && (
				<div className="filter-row compare-row">
					<select className="text-input" value={condition.field || ""} onChange={(e) => setCondition(index, { field: e.target.value })}>
						<option value="">Vergleichsfeld</option>
						{fieldOptions.map((field) => <option value={field.value} key={field.value}>{field.label || field.value}</option>)}
					</select>
					<select className="text-input compact" value={condition.op || "="} onChange={(e) => setCondition(index, { op: e.target.value })}>
						{OPS.map((op) => <option value={op} key={op}>{op}</option>)}
					</select>
					<ValueSourceInput
						valueSource={condition.valueSource || "literal"}
						rowField={condition.rowField || "iban"}
						value={condition.value || ""}
						op={condition.op}
						onChange={(next) => setCondition(index, next)}
					/>
				</div>
			)}
		</div>
	);
}

function ConditionBuilder({ form, patch, setCondition, addCondition, removeCondition }) {
	const [doctypes, setDoctypes] = useState([]);
	useEffect(() => {
		let alive = true;
		api.searchRuleDoctypes("").then((result) => {
			if (alive) setDoctypes(result.items || []);
		}).catch(() => {
			if (alive) setDoctypes([]);
		});
		return () => { alive = false; };
	}, []);

	return (
		<div className="editor-block">
			<div className="eb-kicker">Wenn</div>
			<div className="eb-title">Bedingungen</div>
			<div className="eb-sub">Die Regel greift nur, wenn diese Prüfung für eine Bankzeile zutrifft.</div>
			{form.builder.conditions.map((condition, index) => (
				<div className={`cond-card ${normalizeSource(condition) === "doctype" ? "doc" : ""}`} key={index}>
					<div className="cond-toolbar">
						<select className="text-input compact" value={normalizeSource(condition)} onChange={(e) => setCondition(index, e.target.value === "doctype" ? defaultCondition("doctype") : defaultCondition("row"))}>
							<option value="row">Bankzeile</option>
							<option value="doctype">DocType</option>
						</select>
						<button type="button" className="icon-btn" disabled={form.builder.conditions.length <= 1} onClick={() => removeCondition(index)}><Icon name="x" size={13} /></button>
					</div>
					{normalizeSource(condition) === "doctype" ? (
						<DoctypeConditionEditor condition={condition} index={index} doctypes={doctypes} setCondition={setCondition} />
					) : (
						<div className="cond-row">
							<select className="text-input" value={condition.field} onChange={(e) => setCondition(index, { field: e.target.value, value: "" })}>
								{FIELDS.map((field) => <option value={field} key={field}>{FIELD_LABELS[field]}</option>)}
							</select>
							<select className="text-input" value={condition.op} onChange={(e) => setCondition(index, { op: e.target.value })}>
								{OPS.map((op) => <option value={op} key={op}>{op}</option>)}
							</select>
							{["ist leer", "ist nicht leer"].includes(condition.op) ? (
								<div className="value-empty-note">kein Wert nötig</div>
							) : condition.field === "richtung" ? (
								<select className="text-input" value={condition.value} onChange={(e) => setCondition(index, { value: e.target.value })}>
									<option value="">Richtung</option>
									<option value="Eingang">Eingang</option>
									<option value="Ausgang">Ausgang</option>
								</select>
							) : (
								<input className="text-input" type={condition.field === "betrag" ? "number" : "text"} value={condition.value} onChange={(e) => setCondition(index, { value: e.target.value })} />
							)}
						</div>
					)}
				</div>
			))}
			<div className="builder-actions">
				<button type="button" className="btn subtle sm" onClick={() => addCondition("row")}><Icon name="plus" size={13} /> Bankzeile</button>
				<button type="button" className="btn subtle sm" onClick={() => addCondition("doctype")}><Icon name="plus" size={13} /> DocType</button>
				{form.builder.conditions.length > 1 && (
					<div className="seg">
						<button type="button" className={`seg-btn ${form.builder.connector === "und" ? "active" : ""}`} onClick={() => patch({ builder: { ...form.builder, connector: "und" } })}>alle Bedingungen</button>
						<button type="button" className={`seg-btn ${form.builder.connector === "oder" ? "active" : ""}`} onClick={() => patch({ builder: { ...form.builder, connector: "oder" } })}>eine Bedingung</button>
					</div>
				)}
			</div>
		</div>
	);
}

function ActionBuilder({ form, patch }) {
	if (form.requiresReview) {
		return (
			<div className="editor-block">
				<div className="eb-kicker">Dann</div>
				<div className="eb-title">Zur Prüfung vorlegen</div>
				<div className="eb-sub">Treffer werden nicht automatisch gebucht, sondern bleiben in der Prüfung.</div>
			</div>
		);
	}
	return (
		<div className="editor-block">
			<div className="eb-kicker">Dann</div>
			<div className="eb-title">Aktion</div>
			<div className="seg action-seg">
				{form.kind === "booking" && <button type="button" className={`seg-btn ${["buchung", "booking"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { type: "buchung", account: form.action.account || "", cost_center: form.action.cost_center || "Allgemein" } })}>Auf Konto buchen</button>}
				{form.kind === "party" && <button type="button" className={`seg-btn ${["party", "partei"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { type: "party", party_type: form.action.party_type || "Customer", party: form.action.party || "" } })}>Feste Partei</button>}
				{form.kind === "party" && <button type="button" className={`seg-btn ${["party_from_row", "partei_aus_zeile"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { type: "party_from_row" } })}>Aus Bankzeile</button>}
				{form.kind === "party" && <button type="button" className={`seg-btn ${["party_from_doctype", "partei_aus_doctype"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { type: "party_from_doctype", doctype: "Bank Account", filters: [defaultDoctypeFilter()], partyTypeField: "party_type", partyField: "party" } })}>Aus DocType</button>}
				{["builtin", "system"].includes(form.action.type) && <button type="button" className="seg-btn active">Backend-Aktion</button>}
			</div>
			{["builtin", "system"].includes(form.action.type) ? (
				<div className="backend-action">
					<div className="sb-row">
						<div className="sb-label">Aktion</div>
						<div className="sb-value">{actionText(form.action)}</div>
					</div>
					<div className="eb-sub">Die Bedingungen oben sind editierbar; die Ausführung nutzt eine Backend-Aktion.</div>
				</div>
			) : ["party", "partei"].includes(form.action.type) ? (
				<div className="re-grid">
					<label><span className="field-label">Party Type</span><select className="text-input" value={form.action.party_type || ""} onChange={(e) => patch({ action: { ...form.action, party_type: e.target.value } })}>{PARTY_TYPES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
					<label><span className="field-label">Party</span><input className="text-input" value={form.action.party || ""} onChange={(e) => patch({ action: { ...form.action, party: e.target.value } })} /></label>
				</div>
			) : ["party_from_row", "partei_aus_zeile"].includes(form.action.type) ? (
				<div className="scope-empty">Übernimmt Party Type und Party direkt aus der Bankimport-Zeile.</div>
			) : ["party_from_doctype", "partei_aus_doctype"].includes(form.action.type) ? (
				<div className="doctype-action">
					<div className="re-grid">
						<label><span className="field-label">DocType</span><input className="text-input" value={form.action.doctype || ""} onChange={(e) => patch({ action: { ...form.action, doctype: e.target.value } })} /></label>
						<label><span className="field-label">Party-Type-Feld</span><input className="text-input" value={form.action.partyTypeField || ""} onChange={(e) => patch({ action: { ...form.action, partyTypeField: e.target.value } })} /></label>
						<label><span className="field-label">Party-Feld</span><input className="text-input" value={form.action.partyField || ""} onChange={(e) => patch({ action: { ...form.action, partyField: e.target.value } })} /></label>
					</div>
					<div className="filter-stack">
						<div className="field-label">Suchfilter für die Aktion</div>
						{(form.action.filters || []).map((filter, index) => (
							<div className="filter-row" key={index}>
								<input className="text-input" value={filter.field || ""} onChange={(e) => patch({ action: { ...form.action, filters: form.action.filters.map((item, idx) => idx === index ? { ...item, field: e.target.value } : item) } })} placeholder="iban" />
								<select className="text-input compact" value={filter.op || "="} onChange={(e) => patch({ action: { ...form.action, filters: form.action.filters.map((item, idx) => idx === index ? { ...item, op: e.target.value } : item) } })}>
									{FILTER_OPS.map((op) => <option value={op} key={op}>{op}</option>)}
								</select>
								<ValueSourceInput
									valueSource={filter.valueSource || "literal"}
									rowField={filter.rowField || "iban"}
									value={filter.value || ""}
									op={filter.op}
									onChange={(next) => patch({ action: { ...form.action, filters: form.action.filters.map((item, idx) => idx === index ? { ...item, ...next } : item) } })}
								/>
								<button type="button" className="icon-btn" disabled={(form.action.filters || []).length <= 1} onClick={() => patch({ action: { ...form.action, filters: form.action.filters.filter((_, idx) => idx !== index) } })}><Icon name="x" size={13} /></button>
							</div>
						))}
						<button type="button" className="btn subtle sm" onClick={() => patch({ action: { ...form.action, filters: [...(form.action.filters || []), defaultDoctypeFilter()] } })}><Icon name="plus" size={13} /> Filter</button>
					</div>
				</div>
			) : (
				<div className="re-grid">
					<label><span className="field-label">Gegenkonto</span><input className="text-input" value={form.action.account || ""} onChange={(e) => patch({ action: { ...form.action, account: e.target.value } })} placeholder="4970 Bankgebühren - HV" /></label>
					<label><span className="field-label">Kostenstelle</span><input className="text-input" value={form.action.cost_center || ""} onChange={(e) => patch({ action: { ...form.action, cost_center: e.target.value } })} /></label>
				</div>
			)}
		</div>
	);
}

function BehaviorBuilder({ form, patch }) {
	return (
		<div className="editor-block">
			<div className="eb-kicker">Verhalten</div>
			<div className="eb-title">Ausführung</div>
			<div className="option-grid">
				<label><input type="checkbox" checked={form.enabled} onChange={(e) => patch({ enabled: e.target.checked })} /> Aktiv</label>
				<label><input type="checkbox" checked={form.stopOnMatch} onChange={(e) => patch({ stopOnMatch: e.target.checked })} /> Stoppt bei Treffer</label>
				{form.kind === "booking" && <label><input type="checkbox" checked={form.autoApply} onChange={(e) => patch({ autoApply: e.target.checked })} /> Automatisch anwenden</label>}
				<label><input type="checkbox" checked={form.requiresReview} onChange={(e) => patch({ requiresReview: e.target.checked })} /> Prüfung erforderlich</label>
			</div>
		</div>
	);
}

function ScopeBuilder({ form, patch, setScope }) {
	return (
		<div className="editor-block">
			<div className="eb-head">
				<div>
					<div className="eb-kicker">Geltungsbereich</div>
					<div className="eb-title">Scope</div>
				</div>
				<button type="button" className="btn subtle sm" onClick={() => patch({ scope: [...form.scope, { enabled: true, mode: "Sperren", scopeType: "IBAN", iban: "" }] })}><Icon name="plus" size={13} /> Regel</button>
			</div>
			{form.scope.length === 0 ? <div className="scope-empty">Gilt für alle Zeilen.</div> : form.scope.map((entry, index) => (
				<div className="scope-row" key={index}>
					<select className="text-input" value={entry.mode || "Sperren"} onChange={(e) => setScope(index, { mode: e.target.value })}><option>Sperren</option><option>Erlauben</option></select>
					<select className="text-input" value={entry.scopeType || "IBAN"} onChange={(e) => setScope(index, { scopeType: e.target.value })}><option>IBAN</option><option>Party</option><option>Party Type</option></select>
					{entry.scopeType === "Party Type" ? (
						<select className="text-input" value={entry.partyType || ""} onChange={(e) => setScope(index, { partyType: e.target.value })}>{PARTY_TYPES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
					) : entry.scopeType === "Party" ? (
						<input className="text-input" value={entry.party || ""} onChange={(e) => setScope(index, { party: e.target.value })} placeholder={scopeLabel(entry)} />
					) : (
						<input className="text-input mono" value={entry.iban || ""} onChange={(e) => setScope(index, { iban: e.target.value })} />
					)}
					<button type="button" className="icon-btn" onClick={() => patch({ scope: form.scope.filter((_, idx) => idx !== index) })}><Icon name="trash" size={13} /></button>
				</div>
			))}
		</div>
	);
}

function RuleDesigner({ form, patch, setCondition, addCondition, removeCondition, setScope, builderError, localHits, serverPreview, preview }) {
	return (
		<div className="rule-designer">
			<div className="designer-flow">
				<ConditionBuilder form={form} patch={patch} setCondition={setCondition} addCondition={addCondition} removeCondition={removeCondition} />
				<div className="flow-arrow">↓</div>
				<ActionBuilder form={form} patch={patch} />
				<div className="flow-arrow">↓</div>
				<BehaviorBuilder form={form} patch={patch} />
				<ScopeBuilder form={form} patch={patch} setScope={setScope} />
				<div className={`re-live ${builderError ? "bad" : "ok"}`}>
					{builderError || (serverPreview?.ok
						? `gültig · trifft ${serverPreview.hits} Zeilen im aktuellen Auszug`
						: localHits === null
							? "gültig · DocType-Abfragen bitte serverseitig prüfen"
							: `gültig · trifft ${localHits} Zeilen im aktuellen Auszug`)}
					<button type="button" className="link-btn" onClick={preview}>Server prüfen</button>
				</div>
			</div>
		</div>
	);
}

function MetadataEditor({ form, patch }) {
	return (
		<details className="metadata-panel">
			<summary>Metadaten</summary>
			<div className="metadata-body">
				<div className="re-grid top">
					<label><span className="field-label">Titel</span><input className="text-input" value={form.title} onChange={(e) => patch({ title: e.target.value })} required /></label>
					<label><span className="field-label">Priorität</span><input className="text-input mono" type="number" value={form.priority} onChange={(e) => patch({ priority: Number(e.target.value) || 0 })} /></label>
				</div>
				<label className="re-field"><span className="field-label">Regel-Schlüssel</span><input className="text-input mono" value={form.ruleKey} onChange={(e) => patch({ ruleKey: e.target.value })} /></label>
				<label className="re-field"><span className="field-label">Beschreibung</span><textarea className="text-input re-textarea" value={form.description} onChange={(e) => patch({ description: e.target.value })} /></label>
			</div>
		</details>
	);
}

function RuleEditor({ state, rows, onClose, onSave }) {
	const [form, setForm] = useState(() => makeInitialEditorState(state));
	const [saving, setSaving] = useState(false);
	const [serverPreview, setServerPreview] = useState(null);

	useEffect(() => {
		setForm(makeInitialEditorState(state));
		setServerPreview(null);
	}, [state]);

	useEffect(() => {
		const onKey = (event) => { if (event.key === "Escape") onClose(); };
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose]);

	const builderError = validateBuilder(form.builder);
	const localHits = !builderError && !builderNeedsServer(form.builder) ? (rows || []).filter((row) => !isDoneRow(row) && builderMatches(form.builder, row)).length : null;
	const actionType = form.action.type;
	const actionValid = form.requiresReview
		|| (["party", "partei"].includes(actionType) && Boolean(form.action.party_type && form.action.party))
		|| (["party_from_row", "partei_aus_zeile"].includes(actionType))
		|| (["party_from_doctype", "partei_aus_doctype"].includes(actionType) && Boolean(form.action.doctype && form.action.partyTypeField && form.action.partyField && form.action.filters?.length))
		|| (["builtin", "system"].includes(actionType) && Boolean(form.action.ruleKey || form.ruleKey))
		|| (["buchung", "booking"].includes(actionType) && Boolean(form.action.account || form.action.konto));
	const valid = form.title.trim() && form.ruleKey.trim() && !builderError && actionValid;

	const patch = (next) => setForm((current) => ({ ...current, ...next }));
	const setCondition = (index, next) => patch({
		builder: {
			...form.builder,
			conditions: form.builder.conditions.map((condition, idx) => idx === index ? { ...condition, ...next } : condition),
		},
	});
	const addCondition = (source = "row") => patch({ builder: { ...form.builder, conditions: [...form.builder.conditions, defaultCondition(source)] } });
	const removeCondition = (index) => patch({ builder: { ...form.builder, conditions: form.builder.conditions.filter((_, idx) => idx !== index) } });
	const setScope = (index, next) => patch({ scope: form.scope.map((entry, idx) => idx === index ? { ...entry, ...next } : entry) });

	const preview = async () => {
		if (builderError) return;
		try {
			const parameters = { builder: form.builder, action: form.action, ui: { mode: form.mode } };
			setServerPreview(await api.previewBankimportRuleHits(form.doctype, parameters, undefined, form.name));
		} catch (e) {
			setServerPreview({ ok: false, message: e.message || String(e), hits: 0 });
		}
	};

	const submit = async (event) => {
		event.preventDefault();
		if (!valid || saving) return;
		setSaving(true);
		try {
			await onSave({
				...form,
				forceBuilder: form.forceBuilder,
				parametersJson: { builder: form.builder, action: form.action, ui: { mode: form.mode } },
			});
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="modal-backdrop rule-editor-backdrop" onMouseDown={(event) => { event.stopPropagation(); onClose(); }}>
			<form className="rule-editor" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
				<div className="re-head">
					<div>
						<h2>{form.name ? "Regel bearbeiten" : "Neue Regel"}</h2>
						<div className="re-sub">{form.kind === "party" ? "Party Matching" : "Buchungs-Matching"}</div>
					</div>
					<button type="button" className="btn ghost icon" onClick={onClose} title="Schließen"><Icon name="x" /></button>
				</div>

				<div className="re-body">
					<RuleDesigner
						form={form}
						patch={patch}
						setCondition={setCondition}
						addCondition={addCondition}
						removeCondition={removeCondition}
						setScope={setScope}
						builderError={builderError}
						localHits={localHits}
						serverPreview={serverPreview}
						preview={preview}
					/>
					<MetadataEditor form={form} patch={patch} />
				</div>

				<div className="re-actions">
					<button type="button" className="btn subtle" onClick={onClose}>Abbrechen</button>
					<button type="submit" className="btn primary" disabled={!valid || saving}>{saving ? <Spinner /> : <Icon name="check" />} Speichern</button>
				</div>
			</form>
		</div>
	);
}

export function RulePanel({ open, onClose, notify, rows = [] }) {
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [busyKey, setBusyKey] = useState("");
	const [viewMode, setViewMode] = useState("list");
	const [editor, setEditor] = useState(null);

	const load = useCallback(async () => {
		setLoading(true);
		setError("");
		try {
			setData(await api.listBankimportRules());
		} catch (e) {
			setError(e.message || String(e));
		 } finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		if (open) load();
	}, [open, load]);

	const groups = useMemo(() => {
		const raw = data?.groups || {};
		return GROUP_ORDER.map((key) => raw[key]).filter(Boolean);
	}, [data]);

	if (!open) return null;

	const toggleRule = async (rule, enabled) => {
		const key = `${rule.doctype}:${rule.name}`;
		setBusyKey(key);
		try {
			await api.setBankimportRuleEnabled(rule.doctype, rule.name, enabled);
			notify?.("success", enabled ? "Regel aktiviert." : "Regel deaktiviert.");
			await load();
		} catch (e) {
			notify?.("error", e.message || String(e));
		} finally {
			setBusyKey("");
		}
	};

	const reorderRule = async (rule, direction) => {
		const key = `${rule.doctype}:${rule.name}`;
		setBusyKey(key);
		try {
			await api.reorderBankimportRule(rule.doctype, rule.name, direction);
			await load();
		} catch (e) {
			notify?.("error", e.message || String(e));
		} finally {
			setBusyKey("");
		}
	};

	const deleteRule = async (rule) => {
		if (!window.confirm(`Regel "${titleOf(rule)}" löschen?`)) return;
		try {
			await api.deleteBankimportRule(rule.doctype, rule.name);
			notify?.("success", "Regel gelöscht.");
			await load();
		} catch (e) {
			notify?.("error", e.message || String(e));
		}
	};

	const saveRule = async (values) => {
		try {
			await api.saveBankimportRule(values.doctype, values);
			notify?.("success", "Regel gespeichert.");
			setEditor(null);
			await load();
		} catch (e) {
			notify?.("error", e.message || String(e));
			throw e;
		}
	};

	return (
		<div className="modal-backdrop" onMouseDown={onClose}>
			<div className="rule-modal" onMouseDown={(e) => e.stopPropagation()}>
				<div className="rule-modal-head">
					<div>
						<h2>Bankimport-Regeln</h2>
						<div className="rule-modal-sub">Priorisierte Zuordnung für Party Matching und Buchungs-Matching.</div>
					</div>
					<div className="rule-modal-actions">
						<div className="seg rule-view-toggle">
							<button className={`seg-btn ${viewMode === "list" ? "active" : ""}`} onClick={() => setViewMode("list")}>Liste</button>
							<button className={`seg-btn ${viewMode === "graph" ? "active" : ""}`} onClick={() => setViewMode("graph")}>Graph</button>
						</div>
						<button className="btn subtle" onClick={load} disabled={loading}>{loading ? <Spinner /> : <Icon name="refresh" />} Neu laden</button>
						<button className="btn ghost icon" onClick={onClose} title="Schließen"><Icon name="x" /></button>
					</div>
				</div>

				{error ? (
					<div className="rule-error"><Icon name="info" /> {error}</div>
				) : loading && !data ? (
					<div className="panel-loading"><Spinner size={18} /> Regeln laden...</div>
				) : viewMode === "graph" ? (
					<div className="rule-graph-grid">{groups.map((group) => <GraphColumn group={group} key={group.doctype} />)}</div>
				) : (
					<div className="rule-grid">{groups.map((group) => (
						<RuleColumn
							key={group.doctype}
							group={group}
							rows={rows}
							onNew={(nextGroup) => setEditor({ doctype: nextGroup.doctype, kind: DOCTYPE_KIND[nextGroup.doctype] })}
							onEdit={(rule) => setEditor({ doctype: rule.doctype, rule })}
							onToggle={toggleRule}
							onReorder={reorderRule}
							onDelete={deleteRule}
							busy={Boolean(busyKey)}
						/>
					))}</div>
				)}
			</div>
			{editor && <RuleEditor state={editor} rows={rows} onClose={() => setEditor(null)} onSave={saveRule} />}
		</div>
	);
}
