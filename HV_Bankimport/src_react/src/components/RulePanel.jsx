import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api.js";
import { Icon, Spinner, fmtDateTime } from "../helpers.jsx";

const GROUP_ORDER = ["party", "booking"];

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
						{disabled && <span className="rule-tag off">Aus</span>}
					</div>
					<div className="rule-subline">
						<span>{ruleTypeLabel(rule.doctype)}</span>
						<span>{rule.hasRuleCode ? `${rule.ruleCodeLines || 1} Code-Zeilen` : "Kein Code"}</span>
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
				<span>{rule.hasRuleCode ? "DB-Code" : "Code fehlt"}</span>
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

function GraphNode({ rule, index, total, onOpen, onToggle, toggling }) {
	const scope = rule.scope || [];
	const disabled = !rule.enabled;
	return (
		<div className={`rule-graph-node ${disabled ? "is-disabled" : ""}`}>
			<div className="rgn-top">
				<div className="rgn-priority">{rule.priority ?? "—"}</div>
				<button className="rgn-name" onClick={() => onOpen(rule)}>
					{rule.ruleKey || rule.name}
				</button>
				<label className="rule-switch rgn-switch" title={rule.enabled ? "Regel deaktivieren" : "Regel aktivieren"}>
					<input
						type="checkbox"
						checked={Boolean(rule.enabled)}
						disabled={toggling}
						onChange={(e) => onToggle(rule, e.target.checked)}
					/>
					<span />
				</label>
			</div>
			<div className="rgn-meta">
				<span>{rule.hasRuleCode ? `${rule.ruleCodeLines || 1} Code-Zeilen` : "Code fehlt"}</span>
				<span>{scope.length ? `${scope.length} Scope` : "Kein Scope"}</span>
				{rule.autoApply !== null && rule.autoApply !== undefined && (
					<span>{rule.autoApply ? "Auto" : "Manuell"}</span>
				)}
			</div>
			<div className="rgn-body">
				<div className="rgn-output">{rule.stopOnMatch ? "Treffer stoppt Phase" : "Treffer laeuft weiter"}</div>
				{scope.length > 0 && <div className="rgn-scope">{scopeLabel(scope[0])}</div>}
			</div>
			<div className="rgn-actions">
				<button className="btn subtle sm" onClick={() => onOpen(rule)}>
					<Icon name="file" /> Code & Scope
				</button>
			</div>
			{index < total - 1 && (
				<div className="rgn-edge" aria-hidden="true">
					<span />
					<Icon name="arrowDown" size={13} />
				</div>
			)}
		</div>
	);
}

function RuleGraph({ groups, onOpen, onNew, onList, onToggle, toggling }) {
	return (
		<div className="rule-graph">
			<div className="rule-graph-start">
				<div className="rgs-dot" />
				<div>
					<div className="rgs-title">Bankimport-Zeile</div>
					<div className="rgs-sub">wird von oben nach unten durch die Phasen geführt</div>
				</div>
			</div>
			<div className="rule-graph-lanes">
				{groups.map((group, groupIndex) => {
					const items = group.items || [];
					return (
						<section className="rule-graph-lane" key={group.doctype}>
							<div className="rgl-head">
								<div>
									<h3>{group.label}</h3>
									<div>{group.counts?.enabled || 0} aktiv · {items.length} Knoten</div>
								</div>
								<div className="rgl-actions">
									<button className="btn subtle sm" onClick={() => onList(group.doctype)}>
										<Icon name="file" /> Liste
									</button>
									<button className="btn primary sm" onClick={() => onNew(group.doctype)}>
										<Icon name="plus" /> Neu
									</button>
								</div>
							</div>
							{items.length === 0 ? (
								<div className="rule-empty">Keine Regeln in dieser Phase.</div>
							) : (
								<div className="rule-graph-stack">
									{items.map((rule, index) => (
										<GraphNode
											key={`${rule.doctype}:${rule.name}`}
											rule={rule}
											index={index}
											total={items.length}
											onOpen={onOpen}
											onToggle={onToggle}
											toggling={toggling === `${rule.doctype}:${rule.name}`}
										/>
									))}
								</div>
							)}
							{groupIndex < groups.length - 1 && (
								<div className="rgl-phase-edge" aria-hidden="true">
									<span />
									<Icon name="arrowDown" size={14} />
								</div>
							)}
						</section>
					);
				})}
			</div>
		</div>
	);
}

export function RulePanel({ open, onClose, notify }) {
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [toggling, setToggling] = useState("");
	const [viewMode, setViewMode] = useState("graph");

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
						<div className="seg rule-view-toggle">
							<button
								className={`seg-btn ${viewMode === "graph" ? "active" : ""}`}
								onClick={() => setViewMode("graph")}
							>
								Graph
							</button>
							<button
								className={`seg-btn ${viewMode === "list" ? "active" : ""}`}
								onClick={() => setViewMode("list")}
							>
								Liste
							</button>
						</div>
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
				) : viewMode === "graph" ? (
					<RuleGraph
						groups={groups}
						onOpen={openRule}
						onNew={newRule}
						onList={openList}
						onToggle={toggleRule}
						toggling={toggling}
					/>
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
