import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { Icon, Spinner, fmtDateTime } from "../helpers.jsx";

const GROUP_ORDER = ["party", "booking"];

function matcherLabel(value) {
	return ({
		row_party: "Zeilen-Partei",
		unique_iban_to_party: "IBAN -> Party",
		invoice_auto_match: "Rechnung",
		kreditrate_auto_match: "Kreditrate",
		abschlagsplan_auto_match: "Abschlagsplan",
		needs_review_fallback: "Review-Fallback",
	}[value] || value || "—");
}

function ruleTypeLabel(doctype) {
	return doctype === "Bankimport Buchungsregel" ? "Buchungsregel" : "Party-Regel";
}

function scopeLabel(entry) {
	if (!entry) return "";
	const mode = entry.mode || "Sperren";
	const type = entry.scopeType || "";
	if (type === "IBAN") return `${mode}: ${entry.iban || "IBAN"}`;
	if (type === "Party Type") return `${mode}: ${entry.partyType || "Party Type"}`;
	if (type === "Party") {
		return `${mode}: ${[entry.partyType, entry.party].filter(Boolean).join(" / ") || "Party"}`;
	}
	return `${mode}: ${type || "Scope"}`;
}

function RuleCard({ rule, onOpen, onToggle, toggling }) {
	const [showScope, setShowScope] = useState(false);
	const scope = rule.scope || [];
	const disabled = !rule.enabled;
	return (
		<div className={`rule-card ${disabled ? "is-disabled" : ""}`}>
			<div className="rule-card-head">
				<div className="rule-order">{rule.priority ?? "—"}</div>
				<div className="rule-title-block">
					<div className="rule-title-row">
						<button className="rule-title" onClick={() => onOpen(rule)}>
							{rule.ruleKey || rule.name}
						</button>
						{rule.isSystemRule && <span className="rule-tag">System</span>}
						{disabled && <span className="rule-tag off">Aus</span>}
					</div>
					<div className="rule-subline">
						<span>{matcherLabel(rule.matcherFunction)}</span>
						<span>{ruleTypeLabel(rule.doctype)}</span>
						{rule.modified && <span>{fmtDateTime(rule.modified)}</span>}
					</div>
				</div>
				<label className="rule-switch" title={rule.enabled ? "Regel deaktivieren" : "Regel aktivieren"}>
					<input
						type="checkbox"
						checked={Boolean(rule.enabled)}
						disabled={toggling}
						onChange={(e) => onToggle(rule, e.target.checked)}
					/>
					<span />
				</label>
			</div>

			{rule.description && <div className="rule-desc">{rule.description}</div>}

			<div className="rule-flags">
				<span>{rule.stopOnMatch ? "Stoppt bei Treffer" : "Läuft weiter"}</span>
				{rule.autoApply !== null && rule.autoApply !== undefined && (
					<span>{rule.autoApply ? "Automatisch" : "Manuell"}</span>
				)}
				{rule.requiresReview && <span>Prüfung</span>}
				<span>{scope.length ? `${scope.length} Scope` : "Kein Scope"}</span>
			</div>

			{scope.length > 0 && (
				<div className="rule-scope">
					<button className="rule-scope-toggle" onClick={() => setShowScope((v) => !v)}>
						<Icon name={showScope ? "chevDown" : "chev"} /> {scopeLabel(scope[0])}
						{scope.length > 1 && <span>+{scope.length - 1}</span>}
					</button>
					{showScope && (
						<div className="rule-scope-list">
							{scope.map((entry, idx) => (
								<div key={`${entry.scopeType}-${idx}`}>{scopeLabel(entry)}</div>
							))}
						</div>
					)}
				</div>
			)}

			<div className="rule-card-actions">
				<button className="btn subtle sm" onClick={() => onOpen(rule)}>
					<Icon name="file" /> Bearbeiten
				</button>
			</div>
		</div>
	);
}

function RuleGroup({ group, onOpen, onNew, onList, onToggle, toggling }) {
	const items = group?.items || [];
	return (
		<section className="rule-group">
			<div className="rule-group-head">
				<div>
					<h3>{group?.label || "Regeln"}</h3>
					<div className="rule-group-meta">
						{group?.counts?.enabled || 0} aktiv · {group?.counts?.disabled || 0} aus
					</div>
				</div>
				<div className="rule-group-actions">
					<button className="btn subtle sm" onClick={() => onList(group.doctype)}>
						<Icon name="file" /> Liste
					</button>
					<button className="btn primary sm" onClick={() => onNew(group.doctype)}>
						<Icon name="plus" /> Neu
					</button>
				</div>
			</div>
			{items.length === 0 ? (
				<div className="rule-empty">Keine Regeln vorhanden.</div>
			) : (
				<div className="rule-list">
					{items.map((rule) => (
						<RuleCard
							key={`${rule.doctype}:${rule.name}`}
							rule={rule}
							onOpen={onOpen}
							onToggle={onToggle}
							toggling={toggling === `${rule.doctype}:${rule.name}`}
						/>
					))}
				</div>
			)}
		</section>
	);
}

export function RulePanel({ open, onClose, notify }) {
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [toggling, setToggling] = useState("");

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

	const openRule = async (rule) => {
		await api.openDoc(rule.doctype, rule.name);
	};
	const newRule = async (doctype) => {
		await api.newDoc(doctype);
	};
	const openList = async (doctype) => {
		await api.openList(doctype);
	};
	const toggleRule = async (rule, enabled) => {
		const key = `${rule.doctype}:${rule.name}`;
		setToggling(key);
		try {
			await api.setBankimportRuleEnabled(rule.doctype, rule.name, enabled);
			notify?.("success", enabled ? "Regel aktiviert." : "Regel deaktiviert.");
			await load();
		} catch (e) {
			notify?.("error", e.message || String(e));
		} finally {
			setToggling("");
		}
	};

	return (
		<div className="modal-backdrop" onMouseDown={onClose}>
			<div className="rule-modal" onMouseDown={(e) => e.stopPropagation()}>
				<div className="rule-modal-head">
					<div>
						<h2>Bankimport-Regeln</h2>
						<div className="rule-modal-sub">Reihenfolge, Aktivierung und Geltungsbereiche der automatischen Zuordnung.</div>
					</div>
					<div className="rule-modal-actions">
						<button className="btn subtle" onClick={load} disabled={loading}>
							{loading ? <Spinner /> : <Icon name="refresh" />} Neu laden
						</button>
						<button className="btn ghost icon" onClick={onClose} title="Schließen">
							<Icon name="x" />
						</button>
					</div>
				</div>

				{error ? (
					<div className="rule-error"><Icon name="info" /> {error}</div>
				) : loading && !data ? (
					<div className="panel-loading"><Spinner size={18} /> Regeln laden...</div>
				) : (
					<div className="rule-grid">
						{groups.map((group) => (
							<RuleGroup
								key={group.doctype}
								group={group}
								onOpen={openRule}
								onNew={newRule}
								onList={openList}
								onToggle={toggleRule}
								toggling={toggling}
							/>
						))}
					</div>
				)}
			</div>
		</div>
	);
}
