import React, { useState, useEffect, useMemo, useCallback } from "react";
import * as api from "./api.js";
import { rowPhase, Icon, Spinner, fmtDate } from "./helpers.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { StatRow } from "./components/StatRow.jsx";
import { PhaseStepper } from "./components/PhaseStepper.jsx";
import { Toolbar } from "./components/Toolbar.jsx";
import { TxTable } from "./components/TxTable.jsx";
import { MatchPanel } from "./components/MatchPanel.jsx";

// ── Toast ───────────────────────────────────────────────────────────────────
function Toast({ toast, onClose }) {
	if (!toast) return null;
	return (
		<div className={`hv-toast ${toast.type}`} onClick={onClose}>
			<Icon name={toast.type === "error" ? "info" : "check"} />
			<span>{toast.msg}</span>
			<button className="hv-toast-x"><Icon name="x" /></button>
		</div>
	);
}

// ── Import-Picker (wenn ?import= fehlt) ───────────────────────────────────────
function ImportPicker({ onPick }) {
	const [items, setItems] = useState(null);
	const [query, setQuery] = useState("");
	const [statusFilter, setStatusFilter] = useState("open");
	useEffect(() => {
		api.listImports().then((d) => setItems(d.items || [])).catch(() => setItems([]));
	}, []);

	const isClosedImport = (it) => {
		const open = Number(it.offene_buchungen || 0);
		const total = Number(it.total_rows || 0);
		const status = String(it.status || "").toLowerCase();
		return status.includes("abgeschlossen") || (total > 0 && open <= 0);
	};

	const filteredItems = useMemo(() => {
		if (!items) return [];
		const q = query.trim().toLowerCase();
		return items.filter((it) => {
			const isClosed = isClosedImport(it);
			if (statusFilter === "open" && isClosed) return false;
			if (statusFilter === "closed" && !isClosed) return false;
			if (!q) return true;
			return [it.title, it.name, it.status]
				.some((v) => String(v || "").toLowerCase().includes(q));
		});
	}, [items, query, statusFilter]);

	const counts = useMemo(() => {
		const all = items || [];
		return {
			all: all.length,
			open: all.filter((it) => !isClosedImport(it)).length,
			closed: all.filter((it) => isClosedImport(it)).length,
		};
	}, [items]);

	return (
		<div className="import-picker">
			<div className="ip-card">
				<div className="ip-head">
					<div>
						<h2>Bankauszug-Import wählen</h2>
						<div className="ip-head-sub">Offene und abgeschlossene Kontoauszüge prüfen.</div>
					</div>
					<button className="btn primary" onClick={() => api.newImport()}>
						<Icon name="plus" /> Neuer Import
					</button>
				</div>
				{items === null ? (
					<div className="panel-loading"><Spinner size={18} /> Importe laden…</div>
				) : items.length === 0 ? (
					<div className="hint">Keine Importe vorhanden. Lege zuerst einen neuen Import an.</div>
				) : (
					<>
						<div className="ip-toolbar">
							<div className="ip-search">
								<Icon name="search" />
								<input
									value={query}
									onChange={(e) => setQuery(e.target.value)}
									placeholder="Import, Objekt, Zeitraum oder Status suchen..."
								/>
							</div>
							<div className="ip-status-tabs">
								{[
									["open", "Offen", counts.open],
									["all", "Alle", counts.all],
									["closed", "Abgeschlossen", counts.closed],
								].map(([value, label, count]) => (
									<button
										key={value}
										className={`ip-status-tab ${statusFilter === value ? "is-active" : ""}`}
										onClick={() => setStatusFilter(value)}
									>
										{label} <span>{count}</span>
									</button>
								))}
							</div>
						</div>
						{filteredItems.length === 0 ? (
							<div className="ip-empty">Keine Importe für diese Auswahl.</div>
						) : (
							<div className="ip-table-wrap">
								<table className="ip-table">
									<thead>
										<tr>
											<th>Import</th>
											<th>Status</th>
											<th className="num">Offen</th>
											<th className="num">Zeilen</th>
											<th>Geändert</th>
										</tr>
									</thead>
									<tbody>
										{filteredItems.map((it) => {
											const open = Number(it.offene_buchungen || 0);
											const done = isClosedImport(it);
											return (
												<tr key={it.name} onClick={() => onPick(it.name)}>
													<td>
														<div className="ip-title">{it.title || it.name}</div>
														<div className="ip-sub">{it.name}</div>
													</td>
													<td>
														<span className={`ip-status ${done ? "done" : "open"}`}>
															{done ? "Abgeschlossen" : "Offen"}
														</span>
														<div className="ip-sub">{it.status || "—"}</div>
													</td>
													<td className={`num ip-open ${open > 0 ? "has-open" : ""}`}>{open}</td>
													<td className="num">{it.total_rows ?? "—"}</td>
													<td className="ip-date">{fmtDate(it.modified)}</td>
												</tr>
											);
										})}
									</tbody>
								</table>
							</div>
						)}
					</>
				)}
			</div>
		</div>
	);
}

// ── App ───────────────────────────────────────────────────────────────────--
export function App() {
	const [docname, setDocname] = useState(api.importName || "");
	const [overview, setOverview] = useState(null);
	const [loading, setLoading] = useState(!!docname);
	const [error, setError] = useState("");
	const [busy, setBusy] = useState(false);

	const [phase, setPhase] = useState(0);
	const [filter, setFilter] = useState("all");
	const [search, setSearch] = useState("");
	const [selectedId, setSelectedId] = useState(null);
	const [toast, setToast] = useState(null);

	const notify = useCallback((type, msg) => {
		setToast({ type, msg });
		window.clearTimeout(notify._t);
		notify._t = window.setTimeout(() => setToast(null), type === "error" ? 7000 : 3500);
	}, []);

	const reload = useCallback(
		async (name = docname) => {
			if (!name) return;
			setLoading(true);
			try {
				const data = await api.loadOverview(name);
				setOverview(data);
				setError("");
				return data;
			} catch (e) {
				setError(e.message || String(e));
				return null;
			} finally {
				setLoading(false);
			}
		},
		[docname]
	);

	useEffect(() => { if (docname) reload(docname); }, [docname]); // eslint-disable-line

	const rows = overview?.rows || [];
	const meta = overview?.import || {};
	const phaseCounts = overview?.phaseCounts || { 1: 0, 2: 0, 3: 0, 4: 0 };

	useEffect(() => { setFilter("all"); }, [phase]);

	const scope = useMemo(
		() => (phase === 0 ? rows : rows.filter((r) => rowPhase(r) === phase)),
		[rows, phase]
	);

	const filterCounts = useMemo(() => ({
		all: scope.length,
		problem: scope.filter((r) => ["phase3-ambiguous", "error", "needs_review", "phase1-no-party"].includes(r.rowStatus)).length,
		noparty: scope.filter((r) => !r.party).length,
		nopay: scope.filter((r) => !r.paymentEntry && !r.journalEntry && r.rowStatus !== "done").length,
		customer: scope.filter((r) => r.partyTyp === "Customer").length,
		supplier: scope.filter((r) => r.partyTyp === "Supplier").length,
	}), [scope]);

	const visibleRows = useMemo(() => {
		let out = scope;
		if (filter === "problem") out = scope.filter((r) => ["phase3-ambiguous", "error", "needs_review", "phase1-no-party"].includes(r.rowStatus));
		else if (filter === "noparty") out = scope.filter((r) => !r.party);
		else if (filter === "nopay") out = scope.filter((r) => !r.paymentEntry && !r.journalEntry && r.rowStatus !== "done");
		else if (filter === "customer") out = scope.filter((r) => r.partyTyp === "Customer");
		else if (filter === "supplier") out = scope.filter((r) => r.partyTyp === "Supplier");

		if (search.trim()) {
			const q = search.toLowerCase();
			out = out.filter((r) =>
				(r.verwendungszweck || "").toLowerCase().includes(q) ||
				(r.auftraggeber || "").toLowerCase().includes(q) ||
				(r.party || "").toLowerCase().includes(q) ||
				(r.iban || "").toLowerCase().includes(q)
			);
		}
		return out;
	}, [scope, filter, search]);

	// Auswahl gültig halten: Das Detailpanel darf nur Zeilen bearbeiten, die in
	// der aktuell gefilterten linken Liste sichtbar sind.
	useEffect(() => {
		if (!visibleRows.length) {
			if (selectedId) setSelectedId(null);
			return;
		}
		if (!selectedId || !visibleRows.some((r) => r.id === selectedId)) {
			setSelectedId(visibleRows[0].id);
		}
	}, [visibleRows, selectedId]);

	const selectedRow = useMemo(
		() => visibleRows.find((r) => r.id === selectedId) || null,
		[visibleRows, selectedId]
	);

	const filterLabels = {
		all: phase === 0 ? "Alle Phasen · Alle Zeilen" : `Phase ${phase} · Alle Zeilen`,
		problem: "Problemzeilen", noparty: "Ohne Partei", nopay: "Ohne Zahlung",
		customer: "Kunde", supplier: "Lieferant",
	};

	// Aktion fertig → Overview neu laden, ggf. nächste offene Zeile wählen.
	const onActionDone = useCallback(async ({ advance = true } = {}) => {
		const prevId = selectedId;
		const data = await reload();
		if (!advance) {
			if (data && data.rows && data.rows.some((r) => r.id === prevId)) setSelectedId(prevId);
			return;
		}
		// Nach dem Buchen automatisch zur nächsten offenen Zeile springen.
		if (data && data.rows) {
			const idx = data.rows.findIndex((r) => r.id === prevId);
			const next = data.rows.slice(idx + 1).find((r) => (r.phase || 3) < 4);
			if (next) setSelectedId(next.id);
		}
	}, [reload, selectedId]);

	const runGlobal = useCallback(async (action) => {
		if (!docname) return;
		setBusy(true);
		try {
			if (action === "create_bank_transactions") {
				let res = await api.createBankTransactions(docname, false);
				if (res && res.warning && (!res.created || !res.created.length)) {
					const w = res.warning;
					const msg = (w.message || "Es gibt Zeilen ohne Partei.") + "\n\nTrotzdem Bank-Transaktionen erstellen?";
					if (!window.confirm(msg)) { setBusy(false); return; }
					res = await api.createBankTransactions(docname, true);
				}
				notify("success", `Bank-Transaktionen erstellt: ${(res.created || []).length}`);
			} else if (action === "parse_csv") {
				await api.parseCsv(docname); notify("success", "CSV neu eingelesen.");
			} else if (action === "refresh_saldo") {
				await api.refreshSaldo(docname); notify("success", "Saldo aktualisiert.");
			} else if (action === "relink_all") {
				const r = await api.relinkAllParties(docname);
				notify("success", `Parteien neu verknüpft: ${r.updated || 0} aktualisiert.`);
			}
			await reload();
		} catch (e) {
			notify("error", e.message || String(e));
		} finally {
			setBusy(false);
		}
	}, [docname, notify, reload]);

	// ── Render ──
	if (!docname) return <><ImportPicker onPick={setDocname} /><Toast toast={toast} onClose={() => setToast(null)} /></>;

	if (loading && !overview) return <div className="app-loading"><Spinner size={22} /> Bankimport laden…</div>;
	if (error) return <div className="app-error"><Icon name="info" /> {error}<button className="btn" style={{ marginLeft: 12 }} onClick={() => reload()}>Erneut</button></div>;

	return (
		<div className="shell">
			<TopBar
				meta={meta}
				busy={busy || loading}
				onReload={() => reload()}
				onNewImport={() => api.newImport()}
				onSwitchImport={api.importName ? null : () => setDocname("")}
			/>
			<StatRow meta={meta} rowsCount={rows.length} phases={phaseCounts} />
			<PhaseStepper currentPhase={phase} setPhase={setPhase} phases={phaseCounts} />

			<div className="global-actions">
				<span className="ga-status">{meta.status}</span>
				<div className="ga-spacer" />
				{(phaseCounts[2] || 0) > 0 && (
					<button className="btn primary sm" onClick={() => runGlobal("create_bank_transactions")} disabled={busy}>
						{busy ? <Spinner /> : <Icon name="bolt" />} Bank-Transaktionen erstellen
					</button>
				)}
				<button className="btn subtle sm" onClick={() => runGlobal("relink_all")} disabled={busy}><Icon name="link" /> Parteien verknüpfen</button>
				<button className="btn subtle sm" onClick={() => runGlobal("refresh_saldo")} disabled={busy}><Icon name="refresh" /> Saldo</button>
				<button className="btn subtle sm" onClick={() => api.openImportForm(docname)}><Icon name="file" /> Formular</button>
			</div>

			<Toolbar
				filter={filter} setFilter={setFilter}
				search={search} setSearch={setSearch}
				counts={filterCounts}
				phaseLabel={phase === 0 ? "Alle Phasen" : `Phase ${phase}`}
			/>
			<div className="split">
				<TxTable
					rows={visibleRows}
					selectedId={selectedId}
					onSelect={setSelectedId}
					filterLabel={filterLabels[filter] || "Bankzeilen"}
				/>
				<div className="match-panel-wrap">
					<MatchPanel
						docname={docname}
						row={selectedRow}
						onActionDone={onActionDone}
						onRunGlobal={runGlobal}
						notify={notify}
					/>
				</div>
			</div>
			<Toast toast={toast} onClose={() => setToast(null)} />
		</div>
	);
}
