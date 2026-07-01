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
};
const FIELDS = ["iban", "auftraggeber", "zweck", "betrag", "richtung"];
const OPS = ["enthält", "beginnt mit", "=", "!=", ">", "<", ">=", "<="];
const PARTY_TYPES = [
	["Customer", "Mieter / Kunde"],
	["Supplier", "Lieferant"],
	["Eigentuemer", "Eigentümer"],
];
const SYSTEM_RULES = {
	"party.unique_iban_to_party": {
		label: "Systembaustein",
		when: "IBAN der Bankzeile ist genau einem Bank Account zugeordnet",
		then: "Partei und Party-Typ aus dem Bank Account übernehmen",
		behavior: "Stoppt die Party-Pipeline bei einem eindeutigen Treffer.",
	},
	"party.row_party": {
		label: "Systembaustein",
		when: "Bankzeile hat bereits Partei und Party-Typ",
		then: "Vorhandene Partei der Bankzeile übernehmen",
		behavior: "Stoppt die Party-Pipeline, wenn die Zeile schon fachlich zugeordnet ist.",
	},
	"booking.invoice_auto_match": {
		label: "Systembaustein",
		when: "Offene Sales/Purchase Invoice passt konservativ zur Bank Transaction",
		then: "Payment Entry erstellen und mit der passenden Rechnung abstimmen",
		behavior: "Bucht nur eindeutige Treffer automatisch.",
	},
	"booking.kreditrate_auto_match": {
		label: "Systembaustein",
		when: "Ausgang passt eindeutig zu einer Kreditrate",
		then: "Kreditrate buchen und Journal Entry verknüpfen",
		behavior: "Mehrdeutige Treffer bleiben zur Prüfung offen.",
	},
	"booking.abschlagsplan_auto_match": {
		label: "Systembaustein",
		when: "Supplier-Ausgang passt eindeutig zu einer offenen Abschlagsplan-Zeile",
		then: "Abschlagsplan-Zeile zuordnen und Payment Entry erzeugen",
		behavior: "Läuft nach Rechnungs- und Kreditraten-Match in der Buchungs-Pipeline.",
	},
	"booking.needs_review_fallback": {
		label: "Systembaustein",
		when: "Keine vorherige Buchungsregel konnte die Zeile automatisch buchen",
		then: "Zeile zur manuellen Prüfung markieren",
		behavior: "Fängt offene Buchungsfälle am Ende der Pipeline ab.",
	},
};

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
	return "";
}

function parseNumber(value) {
	const raw = String(value || "0").trim();
	const normalized = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
	return Number.parseFloat(normalized) || 0;
}

function conditionMatches(condition, row) {
	const lhs = fieldValue(condition.field, row);
	const rhs = condition.value ?? "";
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

function validateBuilder(builder) {
	const conditions = builder?.conditions || [];
	if (!conditions.length) return "Mindestens eine Bedingung ist erforderlich.";
	for (const condition of conditions) {
		if (!FIELDS.includes(condition.field)) return "Unbekanntes Feld.";
		if (!OPS.includes(condition.op)) return "Unbekannter Operator.";
		if (condition.value === undefined || condition.value === "") return "Jede Bedingung benötigt einen Wert.";
	}
	return "";
}

function exprText(builder) {
	const connector = ` ${builder?.connector || "und"} `;
	return (builder?.conditions || [])
		.map((condition) => `${FIELD_LABELS[condition.field] || condition.field} ${condition.op} "${condition.value || ""}"`)
		.join(connector);
}

function actionText(action) {
	if (!action) return "";
	if (["party", "partei"].includes(action.type)) return `${action.party_type || action.partyType || "Party"} · ${action.party || ""}`;
	if (["buchung", "booking"].includes(action.type)) return `${action.account || action.konto || ""}${action.cost_center || action.kostenstelle ? ` · ${action.cost_center || action.kostenstelle}` : ""}`;
	return "";
}

function systemRuleInfo(rule) {
	return SYSTEM_RULES[rule?.ruleKey || rule?.name] || null;
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
	const systemInfo = systemRuleInfo(rule);
	const hits = isBuilder && rows?.length
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
			{!isBuilder && systemInfo && (
				<div className="rc-sig rule-recipe">
					<span>Wenn {systemInfo.when}</span>
					<span className="fn-arrow">→</span>
					<span className="fn-out">{systemInfo.then}</span>
				</div>
			)}

			<div className="rc-badges">
				{rule.stopOnMatch && <span className="rc-badge">Stoppt bei Treffer</span>}
				{rule.autoApply && <span className="rc-badge">Automatisch</span>}
				{rule.requiresReview && <span className="rc-badge warn">Prüfung</span>}
				{isBuilder
					? <span className="rc-badge soft">Builder</span>
					: <span className="rc-badge soft">{systemInfo?.label || `DB-Code · ${rule.ruleCodeLines || 0}`}</span>}
				{scope.length > 0 && <span className="rc-badge accent">Scope · {scope.length}</span>}
			</div>

			<div className="rc-foot">
				<div className="rc-foot-left">
					{isBuilder
						? hits > 0 ? <span className="rp-hits has">↻ {hits} {hits === 1 ? "Zeile" : "Zeilen"} im Auszug</span> : <span className="rp-hits">keine Treffer</span>
						: <span className="rc-foot-note">{systemInfo ? "Baustein-Regel" : "Backend-Regel"}</span>}
				</div>
				<div className="rc-actions">
					<button className="btn subtle sm" onClick={() => onEdit(rule)}><Icon name="settings" size={13} /> Bearbeiten</button>
					{!rule.isSystem && isBuilder && (
						<button className="icon-btn danger" onClick={() => onDelete(rule)} title="Löschen" aria-label="Löschen"><Icon name="trash" size={13} /></button>
					)}
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

function defaultCondition() {
	return { field: "auftraggeber", op: "enthält", value: "" };
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
		isSystem: Boolean(rule.isSystem),
		isBuilderRule: Boolean(rule.isBuilderRule || params.builder),
		ruleCodeLines: rule.ruleCodeLines || 0,
		systemInfo: systemRuleInfo(rule),
	};
}

function SystemRuleBuilder({ form }) {
	const info = form.systemInfo;
	if (!info) {
		return (
			<div className="system-builder">
				<div className="sb-row">
					<div className="sb-label">Art</div>
					<div className="sb-value">Backend-Regel mit individuellem Python-Code</div>
				</div>
			</div>
		);
	}
	return (
		<div className="system-builder">
			<div className="sb-row">
				<div className="sb-label">Wenn</div>
				<div className="sb-value">{info.when}</div>
			</div>
			<div className="sb-row">
				<div className="sb-label">Dann</div>
				<div className="sb-value">{info.then}</div>
			</div>
			<div className="sb-row">
				<div className="sb-label">Verhalten</div>
				<div className="sb-value">{info.behavior}</div>
			</div>
		</div>
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

	const builderError = form.isSystem ? "" : validateBuilder(form.builder);
	const localHits = !form.isSystem && !builderError ? (rows || []).filter((row) => !isDoneRow(row) && builderMatches(form.builder, row)).length : 0;
	const actionValid = form.isSystem || form.requiresReview || (
		["party", "partei"].includes(form.action.type)
			? Boolean(form.action.party_type && form.action.party)
			: Boolean(form.action.account || form.action.konto)
	);
	const valid = form.title.trim() && (form.isSystem || form.ruleKey.trim()) && !builderError && actionValid;

	const patch = (next) => setForm((current) => ({ ...current, ...next }));
	const setCondition = (index, next) => patch({
		builder: {
			...form.builder,
			conditions: form.builder.conditions.map((condition, idx) => idx === index ? { ...condition, ...next } : condition),
		},
	});
	const addCondition = () => patch({ builder: { ...form.builder, conditions: [...form.builder.conditions, { field: "zweck", op: "enthält", value: "" }] } });
	const removeCondition = (index) => patch({ builder: { ...form.builder, conditions: form.builder.conditions.filter((_, idx) => idx !== index) } });
	const setScope = (index, next) => patch({ scope: form.scope.map((entry, idx) => idx === index ? { ...entry, ...next } : entry) });

	const preview = async () => {
		if (builderError || form.isSystem) return;
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
					<div className="re-grid top">
						<label><span className="field-label">Titel</span><input className="text-input" value={form.title} onChange={(e) => patch({ title: e.target.value })} required /></label>
						<label><span className="field-label">Priorität</span><input className="text-input mono" type="number" value={form.priority} onChange={(e) => patch({ priority: Number(e.target.value) || 0 })} /></label>
					</div>
					<label className="re-field"><span className="field-label">Regel-Schlüssel</span><input className="text-input mono" value={form.ruleKey} disabled={form.isSystem} onChange={(e) => patch({ ruleKey: e.target.value })} /></label>
					<label className="re-field"><span className="field-label">Beschreibung</span><textarea className="text-input re-textarea" value={form.description} onChange={(e) => patch({ description: e.target.value })} /></label>

					<section className="re-section">
						<div className="re-section-head">
							<span>Wenn</span>
							{!form.isSystem && (
								<div className="seg">
									<button type="button" className={`seg-btn ${form.mode === "einfach" ? "active" : ""}`} onClick={() => patch({ mode: "einfach" })}>Einfach</button>
									<button type="button" className={`seg-btn ${form.mode === "erweitert" ? "active" : ""}`} onClick={() => patch({ mode: "erweitert" })}>Erweitert</button>
								</div>
							)}
						</div>
						{form.isSystem ? (
							<>
								<SystemRuleBuilder form={form} />
								<details className="admin-code-link">
									<summary>Admin-Fallback</summary>
									<div className="locked-rule">
										<span>Backend-Code · {form.ruleCodeLines || 0} Code-Zeilen</span>
										<button
											type="button"
											className="btn subtle sm"
											onClick={() => api.openDoc(form.doctype, form.name)}
										>
											<Icon name="file" size={13} /> Code im Formular öffnen
										</button>
									</div>
								</details>
							</>
						) : form.mode === "erweitert" ? (
							<textarea
								className="text-input re-code"
								value={exprText(form.builder)}
								readOnly
								title="Der erweiterte Freitext wird aus den strukturierten Bedingungen serialisiert."
							/>
						) : (
							<>
								{form.builder.conditions.map((condition, index) => (
									<div className="cond-row" key={index}>
										<select className="text-input" value={condition.field} onChange={(e) => setCondition(index, { field: e.target.value, value: "" })}>
											{FIELDS.map((field) => <option value={field} key={field}>{FIELD_LABELS[field]}</option>)}
										</select>
										<select className="text-input" value={condition.op} onChange={(e) => setCondition(index, { op: e.target.value })}>
											{OPS.map((op) => <option value={op} key={op}>{op}</option>)}
										</select>
										{condition.field === "richtung" ? (
											<select className="text-input" value={condition.value} onChange={(e) => setCondition(index, { value: e.target.value })}>
												<option value="">Richtung</option>
												<option value="Eingang">Eingang</option>
												<option value="Ausgang">Ausgang</option>
											</select>
										) : (
											<input className="text-input" type={condition.field === "betrag" ? "number" : "text"} value={condition.value} onChange={(e) => setCondition(index, { value: e.target.value })} />
										)}
										<button type="button" className="icon-btn" disabled={form.builder.conditions.length <= 1} onClick={() => removeCondition(index)}><Icon name="x" size={13} /></button>
									</div>
								))}
								<div className="builder-actions">
									<button type="button" className="btn subtle sm" onClick={addCondition}><Icon name="plus" size={13} /> Bedingung</button>
									{form.builder.conditions.length > 1 && (
										<div className="seg">
											<button type="button" className={`seg-btn ${form.builder.connector === "und" ? "active" : ""}`} onClick={() => patch({ builder: { ...form.builder, connector: "und" } })}>alle</button>
											<button type="button" className={`seg-btn ${form.builder.connector === "oder" ? "active" : ""}`} onClick={() => patch({ builder: { ...form.builder, connector: "oder" } })}>eine</button>
										</div>
									)}
								</div>
							</>
						)}
						<div className={`re-live ${builderError ? "bad" : "ok"}`}>
							{builderError || `gültig · trifft ${serverPreview?.ok ? serverPreview.hits : localHits} Zeilen im aktuellen Auszug`}
							{!form.isSystem && <button type="button" className="link-btn" onClick={preview}>Server prüfen</button>}
						</div>
					</section>

					{!form.isSystem && !form.requiresReview && (
						<section className="re-section">
							<div className="re-section-head"><span>Dann</span></div>
							<div className="seg action-seg">
								<button type="button" className={`seg-btn ${["buchung", "booking"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { ...form.action, type: "buchung" } })}>Auf Konto buchen</button>
								<button type="button" className={`seg-btn ${["party", "partei"].includes(form.action.type) ? "active" : ""}`} onClick={() => patch({ action: { ...form.action, type: "party" } })}>Partei zuordnen</button>
							</div>
							{["party", "partei"].includes(form.action.type) ? (
								<div className="re-grid">
									<label><span className="field-label">Party Type</span><select className="text-input" value={form.action.party_type || ""} onChange={(e) => patch({ action: { ...form.action, party_type: e.target.value } })}>{PARTY_TYPES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
									<label><span className="field-label">Party</span><input className="text-input" value={form.action.party || ""} onChange={(e) => patch({ action: { ...form.action, party: e.target.value } })} /></label>
								</div>
							) : (
								<div className="re-grid">
									<label><span className="field-label">Gegenkonto</span><input className="text-input" value={form.action.account || ""} onChange={(e) => patch({ action: { ...form.action, account: e.target.value } })} placeholder="4970 Bankgebühren - HV" /></label>
									<label><span className="field-label">Kostenstelle</span><input className="text-input" value={form.action.cost_center || ""} onChange={(e) => patch({ action: { ...form.action, cost_center: e.target.value } })} /></label>
								</div>
							)}
						</section>
					)}

					<section className="re-section">
						<div className="option-grid">
							<label><input type="checkbox" checked={form.enabled} onChange={(e) => patch({ enabled: e.target.checked })} /> Aktiv</label>
							<label><input type="checkbox" checked={form.stopOnMatch} onChange={(e) => patch({ stopOnMatch: e.target.checked })} /> Stoppt bei Treffer</label>
							{form.kind === "booking" && <label><input type="checkbox" checked={form.autoApply} onChange={(e) => patch({ autoApply: e.target.checked })} /> Automatisch anwenden</label>}
							<label><input type="checkbox" checked={form.requiresReview} onChange={(e) => patch({ requiresReview: e.target.checked })} /> Prüfung erforderlich</label>
						</div>
					</section>

					<section className="re-section">
						<div className="re-section-head">
							<span>Geltungsbereich</span>
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
					</section>
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
