import React, { useState, useEffect, useMemo, useCallback } from "react";
import { fmtEUR, fmtDate, fmtDateTime, fmtIban, partyDisplayLabel, partyTypeLabel, Icon, Spinner } from "../helpers.jsx";
import { LinkSearch } from "./LinkSearch.jsx";
import * as api from "../api.js";

// Kleiner Helfer: führt eine async-Aktion aus, setzt busy + meldet Fehler/Erfolg.
function useAction(notify) {
	const [busy, setBusy] = useState(false);
	const run = useCallback(
		async (fn, { success } = {}) => {
			setBusy(true);
			try {
				const res = await fn();
				if (res && res.ok === false) {
					notify("error", res.message || "Aktion nicht möglich.");
					return res;
				}
				if (success) notify("success", success);
				return res;
			} catch (e) {
				notify("error", e.message || String(e));
				return null;
			} finally {
				setBusy(false);
			}
		},
		[notify]
	);
	return [busy, run];
}

function partyActionMessage(base, res) {
	const auto = res?.auto_create || {};
	const created = (auto.created || []).length;
	const matched = (auto.auto_matched || []).length
		+ (auto.auto_abschlag_matched || []).length
		+ (auto.auto_kredit_matched || []).length;
	if (!created) return base;
	if (matched) return `${base} Bank-Transaktion erstellt und automatisch gebucht.`;
	return `${base} Bank-Transaktion erstellt.`;
}

const PARTY_TYPE_OPTIONS = [
	{ id: "Customer", label: "Mieter" },
	{ id: "Supplier", label: "Lieferant" },
	{ id: "Eigentuemer", label: "Eigentümer" },
	{ id: "none", label: "Keine Partei" },
];

const partyOptionLabel = (partyType) =>
	PARTY_TYPE_OPTIONS.find((option) => option.id === partyType)?.label || partyType;

const INVOICE_COLLAPSE_THRESHOLD = 5;

function InvoiceListToggle({ invoices, selectedCount = 0, children }) {
	const count = invoices.length;
	const shouldCollapse = count > INVOICE_COLLAPSE_THRESHOLD;
	const [open, setOpen] = useState(!shouldCollapse);
	const total = useMemo(
		() => invoices.reduce((sum, inv) => sum + (Number(inv.outstanding_amount) || 0), 0),
		[invoices]
	);

	useEffect(() => {
		setOpen(!shouldCollapse);
	}, [shouldCollapse, count, invoices]);

	if (!shouldCollapse) return <>{children}</>;

	return (
		<div className={`invoice-collapse ${open ? "is-open" : ""}`}>
			<button
				type="button"
				className="invoice-collapse-toggle"
				onClick={() => setOpen((value) => !value)}
				aria-expanded={open}
			>
				<span>
					<Icon name={open ? "chevDown" : "chev"} size={13} />
					{count} offene Rechnungen
				</span>
				<strong>{fmtEUR(total)}</strong>
			</button>
			{selectedCount > 0 && !open && (
				<div className="invoice-collapse-note">{selectedCount} ausgewählt</div>
			)}
			{open && <div className="invoice-collapse-list">{children}</div>}
		</div>
	);
}

// ───────────────────────── Smart-Default-Inferenz ───────────────────────────
// Liefert für eine Phase-3-Zeile den wahrscheinlich richtigen Modus + Begründung.
// Bezieht sich auf die Modi-IDs aus BookingActions: invoice|split|abschlag|kredit|payment|journal.

function inferBestMode(row, availableModes) {
	const ids = new Set(availableModes.map((m) => m.id));
	const z = (row.verwendungszweck || "").toLowerCase();
	const auftr = (row.auftraggeber || "").toLowerCase();

	// 1) Konkreter Auto-Match auf eine Rechnung schlägt alles
	if (row.autoMatch && row.autoMatch.rechnungId && ids.has("invoice")) {
		return {
			id: "invoice",
			reason: row.autoMatch.reason || "Offener Beleg dieser Höhe gefunden",
		};
	}
	// 2) Kreditrate – Tilgung/Zins/Annuität/Darlehen
	if (ids.has("kredit") && /tilgung|zins(en)?|annuit|darlehen|kredit|leasing/.test(z)) {
		return { id: "kredit", reason: "Verwendungszweck deutet auf Darlehensrate hin" };
	}
	// 3) Abschlag – Akonto/Vorauszahlung/NKV
	if (ids.has("split") && /sammel|mehrere|aufteil|abschlag.*rechnung|rechnung.*abschlag/.test(z)) {
		return { id: "split", reason: "Verwendungszweck deutet auf eine aufzuteilende Zahlung hin" };
	}
	if (ids.has("abschlag") && /akonto|abschlag|vorauszahlung|nebenkost|nkv|wp[-_ ]?vz/.test(z)) {
		return { id: "abschlag", reason: "Verwendungszweck deutet auf Akonto-/Abschlagszahlung hin" };
	}
	// 4) Buchungssatz – Finanzamt / Steuer
	if (ids.has("journal") && (/finanzamt|umsatzsteuer|vorsteuer|lohnsteuer/.test(z) || /finanzamt/.test(auftr))) {
		return { id: "journal", reason: "Finanzamt – direkt auf Steuer-Konto buchen" };
	}
	// 5) Default: erster verfügbarer Modus, kein lautes Banner
	return { id: availableModes[0]?.id || "journal", reason: null };
}

// ───────────────────────── Phase 1: Partei zuordnen ─────────────────────────

function AuditItem({ label, doc, actionLabel, actor, at, source, onOpen }) {
	if (!doc && !actor && !at && !source) return null;
	const created = doc && (doc.createdBy || doc.createdAt);
	const changed = doc && (doc.modifiedBy || doc.modifiedAt);
	return (
		<div className="audit-item">
			<div className="audit-top">
				<span>{label}</span>
				{source && <span className="audit-source">{source}</span>}
			</div>
			{doc && (
				<button className="audit-doc" onClick={onOpen} title={doc.name}>
					<span className="mono">{doc.name}</span>
					<Icon name="link" size={12} />
				</button>
			)}
			{created && (
				<div className="audit-line">
					<span>Erstellt</span>
					<strong>{doc.createdBy || "—"}</strong>
					<time>{fmtDateTime(doc.createdAt)}</time>
				</div>
			)}
			{changed && (
				<div className="audit-line">
					<span>Geändert</span>
					<strong>{doc.modifiedBy || "—"}</strong>
					<time>{fmtDateTime(doc.modifiedAt)}</time>
				</div>
			)}
			{!doc && (actor || at) && (
				<div className="audit-line">
					<span>{actionLabel || "Zugeordnet"}</span>
					<strong>{actor || "—"}</strong>
					<time>{fmtDateTime(at)}</time>
				</div>
			)}
		</div>
	);
}

function AuditTrail({ row }) {
	const [open, setOpen] = useState(false);
	const audit = row.audit || {};
	const assignment = audit.assignment || {};
	const items = [
		audit.row && (audit.row.createdBy || audit.row.createdAt),
		audit.party || (assignment.by || assignment.at || assignment.source),
		audit.partyRule,
		audit.bookingRule,
		audit.bankTransaction,
		audit.paymentDocument,
	];
	if (!items.some(Boolean)) return null;
	return (
		<div className={`audit-box ${open ? "is-open" : ""}`}>
			<button
				type="button"
				className="audit-title"
				onClick={() => setOpen((value) => !value)}
				aria-expanded={open}
			>
				<span><Icon name="info" size={13} /> Nachvollziehbarkeit</span>
				<Icon name={open ? "chevDown" : "chev"} size={13} />
			</button>
			{open && (
				<div className="audit-content">
					<AuditItem
						label="Importzeile"
						actionLabel="Erstellt"
						actor={audit.row?.createdBy}
						at={audit.row?.createdAt}
					/>
					<AuditItem
						label="Partei"
						doc={audit.party}
						onOpen={() => audit.party && api.openDoc(audit.party.doctype, audit.party.name)}
					/>
					<AuditItem
						label="Zuordnung"
						actionLabel="Zugeordnet"
						actor={assignment.by}
						at={assignment.at}
						source={assignment.source}
					/>
					<AuditItem
						label="Party-Regel"
						doc={audit.partyRule}
						onOpen={() => audit.partyRule && api.openDoc(audit.partyRule.doctype, audit.partyRule.name)}
					/>
					<AuditItem
						label="Buchungsregel"
						doc={audit.bookingRule}
						onOpen={() => audit.bookingRule && api.openDoc(audit.bookingRule.doctype, audit.bookingRule.name)}
					/>
					<AuditItem
						label="Bank-Transaktion"
						doc={audit.bankTransaction}
						onOpen={() => audit.bankTransaction && api.openDoc("Bank Transaction", audit.bankTransaction.name)}
					/>
					<AuditItem
						label="Zahlung"
						doc={audit.paymentDocument}
						onOpen={() => audit.paymentDocument && api.openDoc(audit.paymentDocument.doctype, audit.paymentDocument.name)}
					/>
				</div>
			)}
		</div>
	);
}

function PartyAssign({ docname, row, onActionDone, notify }) {
	const [partyType, setPartyType] = useState(row.betrag < 0 ? "Supplier" : "Customer");
	const [busy, run] = useAction(notify);
	const noPartyMode = partyType === "none";

	const fetcher = useCallback((txt) => api.searchParties(partyType, txt), [partyType]);

	const assign = (item) =>
		run(() => api.assignParty(docname, row.id, partyType, item.value, row.iban))
			.then((r) => {
				if (!r) return;
				notify("success", partyActionMessage(`Partei zugeordnet: ${item.value}.`, r));
				onActionDone();
			});

	const createNew = () =>
		run(() => api.createParty(docname, row.id, partyType, row.auftraggeber))
			.then((r) => {
				if (!r) return;
				notify("success", partyActionMessage("Partei angelegt und zugeordnet.", r));
				onActionDone();
			});

	const createWithoutParty = () =>
		run(async () => api.createBankTransactionForRow(docname, row.id, true))
			.then((r) => {
				if (!r) return;
				const created = (r.created || []).length;
				const matched = (r.auto_matched || []).length
					+ (r.auto_abschlag_matched || []).length
					+ (r.auto_kredit_matched || []).length;
				if (created && matched) notify("success", "Bank-Transaktion ohne Partei erstellt und automatisch gebucht.");
				else if (created) notify("success", "Bank-Transaktion ohne Partei erstellt.");
				else notify("success", "Zeile verarbeitet.");
				onActionDone({ advance: false });
			});

	return (
		<div className="match-section">
			<div className="sec-label">Partei zuordnen</div>
			<div className="seg" role="tablist" style={{ marginBottom: 10 }}>
				{PARTY_TYPE_OPTIONS.map((option) => (
					<button
						key={option.id}
						className={`seg-btn ${partyType === option.id ? "active" : ""}`}
						onClick={() => setPartyType(option.id)}
					>
						{option.label}
					</button>
				))}
			</div>
			{noPartyMode ? (
				<>
					<div className="hint" style={{ marginBottom: 10 }}>
						Für Bankgebühren, Umbuchungen oder neutrale Bewegungen ohne Mieter, Lieferant oder Eigentümer.
					</div>
					<button className="btn sm" style={{ marginBottom: 14 }} onClick={createWithoutParty} disabled={busy}>
						{busy ? <Spinner /> : <Icon name="bolt" />} Bank-Transaktion ohne Partei anlegen
					</button>
					<InternalTransferPayment docname={docname} row={row} onActionDone={onActionDone} notify={notify} />
					<div className="hint" style={{ marginTop: 14, marginBottom: 10 }}>
						Alternativ direkt auf ein Sachkonto buchen:
					</div>
					<JournalEntryForm docname={docname} row={row} onActionDone={onActionDone} notify={notify} />
				</>
			) : (
				<>
					<LinkSearch
						placeholder={`${partyOptionLabel(partyType)} suchen…`}
						fetcher={fetcher}
						onPick={assign}
						autoFocus
						disabled={busy}
					/>
					{row.auftraggeber && partyType !== "Eigentuemer" && (
						<button className="btn sm" style={{ marginTop: 10 }} onClick={createNew} disabled={busy}>
							{busy ? <Spinner /> : <Icon name="plus" />} Neu anlegen aus „{row.auftraggeber}"
						</button>
					)}
					<div className="hint">
						Echte Mieter-, Lieferanten- oder Eigentümerbewegungen sollten einer Partei zugeordnet werden.
						Für neutrale Bewegungen wähle „Keine Partei".
					</div>
				</>
			)}
		</div>
	);
}

function PartyChangeDialog({ docname, row, onClose, onActionDone, notify }) {
	const [partyType, setPartyType] = useState(row.partyTyp || (row.betrag < 0 ? "Supplier" : "Customer"));
	const [updateIbanMapping, setUpdateIbanMapping] = useState(false);
	const [propagateSameIban, setPropagateSameIban] = useState(true);
	const [busy, run] = useAction(notify);
	const hasVoucher = !!(row.paymentEntry || row.journalEntry || row.paymentDocument);
	const noPartyMode = partyType === "none";
	const fetcher = useCallback((txt) => api.searchParties(partyType, txt), [partyType]);

	const finish = (res, success) => {
		if (!res || res.ok === false) return;
		if (success) notify("success", partyActionMessage(success, res));
		onClose();
		onActionDone({ advance: false });
	};

	const changeTo = (item) =>
		run(() => api.changeRowParty(docname, row.id, {
			partyType,
			party: item.value,
			updateIbanMapping,
			propagateSameIban,
		})).then((res) => finish(res, `Partei geändert: ${item.value}`));

	const clearParty = () =>
		run(() => api.changeRowParty(docname, row.id, {
			clearParty: true,
			updateIbanMapping,
			propagateSameIban: false,
		})).then((res) => finish(res, "Partei entfernt."));

	const createNew = () =>
		run(() => api.changeRowParty(docname, row.id, {
			partyType,
			party: row.auftraggeber,
			updateIbanMapping,
			propagateSameIban,
			createIfMissing: true,
		})).then((res) => finish(res, "Partei angelegt und zugeordnet."));

	return (
		<div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
			<div className="party-dialog" role="dialog" aria-modal="true" aria-label="Partei ändern">
				<div className="dialog-head">
					<div>
						<div className="dialog-title">Partei ändern</div>
						<div className="dialog-sub">{fmtDate(row.buchungstag)} · {fmtEUR(row.betrag)}</div>
					</div>
					<button className="btn subtle sm" onClick={onClose} disabled={busy} aria-label="Schließen">
						<Icon name="x" />
					</button>
				</div>
				{hasVoucher && (
					<div className="reset-warning">
						<Icon name="info" /> Bestehende Buchung wird vor der Änderung storniert.
					</div>
				)}
				<div className="current-party">
					<span>Aktuell</span>
					<strong>{row.party ? `${row.party}${partyTypeLabel(row.partyTyp) ? ` · ${partyTypeLabel(row.partyTyp)}` : ""}` : "keine Partei"}</strong>
				</div>
				<div className="seg" role="tablist" style={{ marginBottom: 10 }}>
					{PARTY_TYPE_OPTIONS.map((option) => (
						<button
							key={option.id}
							className={`seg-btn ${partyType === option.id ? "active" : ""}`}
							onClick={() => setPartyType(option.id)}
							disabled={busy}
						>
							{option.label}
						</button>
					))}
				</div>
				{noPartyMode ? (
					<div className="hint" style={{ marginBottom: 10 }}>
						Entfernt die Partei von dieser Importzeile. Bank-Transaktion und Belegzuordnung bleiben erhalten,
						sofern du nicht separat „Beleg lösen" oder „Zeile zurücksetzen" nutzt.
					</div>
				) : (
					<LinkSearch
						placeholder={`${partyOptionLabel(partyType)} suchen…`}
						fetcher={fetcher}
						onPick={changeTo}
						autoFocus
						disabled={busy}
					/>
				)}
				<div className="dialog-options">
					<label className="advance-toggle">
						<input
							type="checkbox"
							checked={updateIbanMapping}
							onChange={(e) => setUpdateIbanMapping(e.target.checked)}
							disabled={busy || !row.iban}
						/>
						IBAN-Verknüpfung ebenfalls ändern/entfernen
					</label>
					{!noPartyMode && (
						<label className="advance-toggle">
							<input
								type="checkbox"
								checked={propagateSameIban}
								onChange={(e) => setPropagateSameIban(e.target.checked)}
								disabled={busy || !row.iban}
							/>
							Ungebuchte Zeilen mit gleicher eindeutiger IBAN aktualisieren
						</label>
					)}
				</div>
				<div className="dialog-actions">
					{!noPartyMode && row.auftraggeber && partyType !== "Eigentuemer" && (
						<button className="btn" onClick={createNew} disabled={busy}>
							{busy ? <Spinner /> : <Icon name="plus" />} Neu anlegen aus Auftraggeber
						</button>
					)}
					{noPartyMode && (
						<button className="btn danger" onClick={clearParty} disabled={busy || (!row.party && !row.partyTyp)}>
							{busy ? <Spinner /> : <Icon name="x" />} Keine Partei übernehmen
						</button>
					)}
				</div>
			</div>
		</div>
	);
}

function ResetRowDialog({ row, mode, busy, onClose, onConfirm }) {
	const bookingOnly = mode === "booking";
	return (
		<div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
			<div className="party-dialog reset-row-dialog" role="dialog" aria-modal="true" aria-label="Importzeile zurücksetzen">
				<div className="dialog-head">
					<div>
						<div className="dialog-title">{bookingOnly ? "Beleg lösen" : "Importzeile zurücksetzen"}</div>
						<div className="dialog-sub">{fmtDate(row.buchungstag)} · {fmtEUR(row.betrag)}</div>
					</div>
					<button className="btn subtle sm" onClick={onClose} disabled={busy} aria-label="Schließen">
						<Icon name="x" />
					</button>
				</div>
				<div className="reset-warning">
					<Icon name="info" /> {bookingOnly
						? "Diese Aktion löst nur den gebuchten Beleg von der Bankzeile."
						: "Diese Aktion nimmt die Verarbeitung dieser Zeile zurück."}
				</div>
				<div className="reset-row-summary">
					<strong>{partyDisplayLabel(row)}</strong>
					<span>{row.verwendungszweck || "Ohne Verwendungszweck"}</span>
				</div>
				<ul className="reset-impact-list">
					{bookingOnly ? (
						<>
							<li>Payment/Journal-Belege werden storniert.</li>
							<li>Bank-Transaktion bleibt erhalten.</li>
							<li>Partei bleibt erhalten.</li>
						</>
					) : (
						<>
							<li>Payment/Journal-Belege werden storniert.</li>
							<li>Import-eigene Bank-Transaktionen werden storniert oder gelöscht.</li>
							<li>Partei, Bank-Transaktion und Zeilen-Links werden entfernt.</li>
						</>
					)}
				</ul>
				<div className="dialog-actions">
					<button className="btn" onClick={onClose} disabled={busy}>Abbrechen</button>
					<button className="btn danger" onClick={onConfirm} disabled={busy}>
						{busy ? <Spinner /> : <Icon name={bookingOnly ? "x" : "trash"} />} {bookingOnly ? "Beleg lösen" : "Zurücksetzen"}
					</button>
				</div>
			</div>
		</div>
	);
}

// ───────────────────────── Phase 3: Rechnungen matchen ──────────────────────

function InvoiceMatch({ docname, row, onActionDone, notify }) {
	const [data, setData] = useState(null);
	const [sel, setSel] = useState({}); // name -> allocated_amount
	const [advance, setAdvance] = useState(false);
	const [loading, setLoading] = useState(true);
	const [busy, run] = useAction(notify);
	const target = Math.abs(Number(row.betrag) || 0);

	useEffect(() => {
		let alive = true;
		setLoading(true);
		setSel({});
		api.getOpenInvoices(docname, row.id)
			.then((d) => alive && setData(d))
			.catch((e) => alive && notify("error", e.message))
			.finally(() => alive && setLoading(false));
		return () => { alive = false; };
	}, [docname, row.id, notify]);

	const allocated = useMemo(
		() => Object.values(sel).reduce((s, v) => s + (Number(v) || 0), 0),
		[sel]
	);
	const remaining = Math.round((target - allocated) * 100) / 100;
	const invoiceByName = useMemo(
		() => new Map((data?.invoices || []).map((inv) => [inv.name, inv])),
		[data]
	);

	const toggle = (inv) => {
		setSel((prev) => {
			const next = { ...prev };
			if (next[inv.name] != null) {
				delete next[inv.name];
			} else {
				const already = Object.values(next).reduce((s, v) => s + (Number(v) || 0), 0);
				const rem = Math.max(0, target - already);
				next[inv.name] = Math.min(Number(inv.outstanding_amount) || 0, rem) || Number(inv.outstanding_amount) || 0;
			}
			return next;
		});
	};

	const setAlloc = (name, val) =>
		setSel((prev) => ({ ...prev, [name]: val === "" ? 0 : Number(val) }));

	const book = () => {
		const invoices = Object.entries(sel).map(([name, allocated_amount]) => ({ name, allocated_amount }));
		if (!invoices.length) return notify("error", "Bitte mindestens eine Rechnung auswählen.");
		for (const inv of invoices) {
			const amount = Number(inv.allocated_amount);
			const source = invoiceByName.get(inv.name);
			const outstanding = Number(source?.outstanding_amount || 0);
			if (!Number.isFinite(amount) || amount <= 0) {
				return notify("error", `Zuweisung für ${inv.name} muss größer als 0 € sein.`);
			}
			if (amount > outstanding + 0.01) {
				return notify("error", `Zuweisung für ${inv.name} übersteigt den offenen Betrag.`);
			}
		}
		if (allocated - target > 0.01) return notify("error", "Die Zuweisung übersteigt den Bankbetrag.");
		run(() => api.reconcileInvoices(docname, row.id, invoices, advance), {
			success: "Zahlung gebucht und Bank Transaction abgeglichen.",
		}).then((r) => r && r.ok !== false && onActionDone());
	};

	if (loading) return <div className="panel-loading"><Spinner size={18} /> Offene Rechnungen laden…</div>;
	if (!data || !data.invoices.length) {
		return (
			<div className="hint">
				Keine offenen {data && data.invoiceDoctype === "Purchase Invoice" ? "Eingangs" : "Ausgangs"}rechnungen
				für diese Partei. Nutze „Vorauszahlung" oder „Buchungssatz".
			</div>
		);
	}

	return (
		<div>
			<div className="alloc-summary">
				<span>Tx-Betrag <strong>{fmtEUR(target)}</strong></span>
				<span>Zugewiesen <strong>{fmtEUR(allocated)}</strong></span>
				<span className={remaining === 0 ? "ok" : remaining < 0 ? "bad" : ""}>
					Rest <strong>{fmtEUR(remaining)}</strong>
				</span>
			</div>
			<InvoiceListToggle invoices={data.invoices} selectedCount={Object.keys(sel).length}>
				{data.invoices.map((inv) => {
					const checked = sel[inv.name] != null;
					return (
						<div key={inv.name} className={`invoice-card ${checked ? "suggested" : "alt"}`}>
							<label className="row1" style={{ cursor: "pointer" }}>
								<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
									<input type="checkbox" checked={checked} onChange={() => toggle(inv)} />
									<div>
										<div className="doc-id">{inv.name}</div>
										<div className="ref">{inv.remarks || "—"}</div>
									</div>
								</div>
								<div className="amount">{fmtEUR(inv.outstanding_amount)}</div>
							</label>
							<div className="meta-row">
								<span className="due"><Icon name="file" size={11} /> {fmtDate(inv.posting_date)}</span>
								{checked && (
									<span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
										zuweisen
										<input
											className="alloc-input"
											type="number"
											step="0.01"
											value={sel[inv.name]}
											onChange={(e) => setAlloc(inv.name, e.target.value)}
										/>
										€
									</span>
								)}
							</div>
						</div>
					);
				})}
			</InvoiceListToggle>
			{remaining > 0.01 && Object.keys(sel).length > 0 && (
				<label className="advance-toggle">
					<input type="checkbox" checked={advance} onChange={(e) => setAdvance(e.target.checked)} />
					Restbetrag {fmtEUR(remaining)} als Vorauszahlung am Konto belassen
				</label>
			)}
			<button
				className="btn primary"
				style={{ width: "100%", justifyContent: "center", marginTop: 8 }}
				onClick={book}
				disabled={busy || !Object.keys(sel).length}
			>
				{busy ? <Spinner /> : <Icon name="check" />} Zuordnen &amp; buchen
			</button>
		</div>
	);
}

// ───────────────────────── Phase 3: Zahlung aufteilen ───────────────────────

function SplitPaymentMatch({ docname, row, onActionDone, notify }) {
	const [data, setData] = useState(null);
	const [invoiceSel, setInvoiceSel] = useState({});
	const [abschlagSel, setAbschlagSel] = useState({});
	const [leftoverAsAdvance, setLeftoverAsAdvance] = useState(false);
	const [loading, setLoading] = useState(true);
	const [busy, run] = useAction(notify);
	const target = Math.abs(Number(row.betrag) || 0);

	useEffect(() => {
		let alive = true;
		setLoading(true);
		setInvoiceSel({});
		setAbschlagSel({});
		setLeftoverAsAdvance(false);
		api.getSplitOptions(docname, row.id)
			.then((d) => alive && setData(d))
			.catch((e) => alive && notify("error", e.message))
			.finally(() => alive && setLoading(false));
		return () => { alive = false; };
	}, [docname, row.id, notify]);

	const invoiceByName = useMemo(
		() => new Map((data?.invoices || []).map((inv) => [inv.name, inv])),
		[data]
	);
	const abschlagByName = useMemo(
		() => new Map((data?.abschlaege || []).map((a) => [a.row_name, a])),
		[data]
	);
	const invoiceTotal = useMemo(
		() => Object.values(invoiceSel).reduce((s, v) => s + (Number(v) || 0), 0),
		[invoiceSel]
	);
	const abschlagTotal = useMemo(
		() => Object.keys(abschlagSel).reduce((s, name) => s + (Number(abschlagByName.get(name)?.betrag) || 0), 0),
		[abschlagSel, abschlagByName]
	);
	const allocated = invoiceTotal + abschlagTotal;
	const remaining = Math.round((target - allocated) * 100) / 100;

	const toggleInvoice = (inv) => {
		setInvoiceSel((prev) => {
			const next = { ...prev };
			if (next[inv.name] != null) {
				delete next[inv.name];
			} else {
				const already = Object.values(next).reduce((s, v) => s + (Number(v) || 0), 0) + abschlagTotal;
				const rem = Math.max(0, target - already);
				next[inv.name] = Math.min(Number(inv.outstanding_amount) || 0, rem) || Number(inv.outstanding_amount) || 0;
			}
			return next;
		});
	};
	const setInvoiceAlloc = (name, val) =>
		setInvoiceSel((prev) => ({ ...prev, [name]: val === "" ? 0 : Number(val) }));

	const toggleAbschlag = (a) => {
		setAbschlagSel((prev) => {
			const next = { ...prev };
			if (next[a.row_name]) delete next[a.row_name];
			else next[a.row_name] = true;
			return next;
		});
	};

	const book = () => {
		const invoices = Object.entries(invoiceSel).map(([name, allocated_amount]) => ({ name, allocated_amount }));
		const abschlaege = Object.keys(abschlagSel).map((row_name) => ({ row_name }));
		if (!invoices.length && !abschlaege.length) return notify("error", "Bitte mindestens eine Rechnung oder einen Abschlag auswählen.");
		for (const inv of invoices) {
			const amount = Number(inv.allocated_amount);
			const source = invoiceByName.get(inv.name);
			const outstanding = Number(source?.outstanding_amount || 0);
			if (!Number.isFinite(amount) || amount <= 0) return notify("error", `Zuweisung für ${inv.name} muss größer als 0 € sein.`);
			if (amount > outstanding + 0.01) return notify("error", `Zuweisung für ${inv.name} übersteigt den offenen Betrag.`);
		}
		if (allocated - target > 0.01) return notify("error", "Die Auswahl übersteigt den Bankbetrag.");
		if (remaining > 0.01 && !leftoverAsAdvance) return notify("error", "Bitte Restbetrag als Vorauszahlung aktivieren oder weitere Positionen wählen.");
		run(() => api.reconcileSplit(docname, row.id, { invoices, abschlaege, leftoverAsAdvance }), {
			success: "Zahlung aufgeteilt und gebucht.",
		}).then((r) => r && r.ok !== false && onActionDone());
	};

	if (loading) return <div className="panel-loading"><Spinner size={18} /> Split-Optionen laden…</div>;
	const hasInvoices = (data?.invoices || []).length > 0;
	const hasAbschlaege = (data?.abschlaege || []).length > 0;
	if (!hasInvoices && !hasAbschlaege) {
		return <div className="hint">Keine offenen Rechnungen oder Abschlagszeilen für diese Partei gefunden.</div>;
	}

	return (
		<div>
			<div className="alloc-summary">
				<span>Tx-Betrag <strong>{fmtEUR(target)}</strong></span>
				<span>Zugewiesen <strong>{fmtEUR(allocated)}</strong></span>
				<span className={remaining === 0 ? "ok" : remaining < 0 ? "bad" : ""}>
					Rest <strong>{fmtEUR(remaining)}</strong>
				</span>
			</div>

			{hasInvoices && <div className="field-label" style={{ marginTop: 10 }}>Rechnungen</div>}
			{hasInvoices && (
				<InvoiceListToggle invoices={data.invoices} selectedCount={Object.keys(invoiceSel).length}>
					{data.invoices.map((inv) => {
						const checked = invoiceSel[inv.name] != null;
						return (
							<div key={inv.name} className={`invoice-card ${checked ? "suggested" : "alt"}`}>
								<label className="row1" style={{ cursor: "pointer" }}>
									<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
										<input type="checkbox" checked={checked} onChange={() => toggleInvoice(inv)} />
										<div>
											<div className="doc-id">{inv.name}</div>
											<div className="ref">{inv.remarks || "—"}</div>
										</div>
									</div>
									<div className="amount">{fmtEUR(inv.outstanding_amount)}</div>
								</label>
								<div className="meta-row">
									<span className="due"><Icon name="file" size={11} /> {fmtDate(inv.posting_date)}</span>
									{checked && (
										<span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
											zuweisen
											<input
												className="alloc-input"
												type="number"
												step="0.01"
												value={invoiceSel[inv.name]}
												onChange={(e) => setInvoiceAlloc(inv.name, e.target.value)}
											/>
											€
										</span>
									)}
								</div>
							</div>
						);
					})}
				</InvoiceListToggle>
			)}

			{hasAbschlaege && <div className="field-label" style={{ marginTop: 12 }}>Abschläge</div>}
			{(data?.abschlaege || []).map((a) => {
				const checked = !!abschlagSel[a.row_name];
				return (
					<div key={a.row_name} className={`invoice-card ${checked ? "suggested" : "alt"}`}>
						<label className="row1" style={{ cursor: "pointer" }}>
							<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
								<input type="checkbox" checked={checked} onChange={() => toggleAbschlag(a)} />
								<div>
									<div className="doc-id">{a.bezeichnung || a.zahlungsplan}</div>
									<div className="ref">Fällig {fmtDate(a.faelligkeitsdatum)}{a.immobilie ? ` · ${a.immobilie}` : ""}</div>
								</div>
							</div>
							<div className="amount">{fmtEUR(a.betrag)}</div>
						</label>
					</div>
				);
			})}

			{remaining > 0.01 && (
				<label className="advance-toggle">
					<input type="checkbox" checked={leftoverAsAdvance} onChange={(e) => setLeftoverAsAdvance(e.target.checked)} />
					Restbetrag {fmtEUR(remaining)} als weitere Vorauszahlung am Konto belassen
				</label>
			)}
			<button
				className="btn primary"
				style={{ width: "100%", justifyContent: "center", marginTop: 8 }}
				onClick={book}
				disabled={busy || (!Object.keys(invoiceSel).length && !Object.keys(abschlagSel).length)}
			>
				{busy ? <Spinner /> : <Icon name="check" />} Aufteilen &amp; buchen
			</button>
		</div>
	);
}

// ───────────────────────── Phase 3: Buchungssatz ────────────────────────────

function JournalEntryForm({ docname, row, onActionDone, notify }) {
	const [account, setAccount] = useState(null);
	const [costCenter, setCostCenter] = useState("");
	const [remarks, setRemarks] = useState(row.verwendungszweck || "");
	const [wertstellungsdatum, setWertstellungsdatum] = useState(row.buchungstag || "");
	const [splitMode, setSplitMode] = useState(false);
	const [splits, setSplits] = useState([
		{ id: 1, account: null, costCenter: "", amount: Math.abs(Number(row.betrag) || 0).toFixed(2) },
	]);
	const [busy, run] = useAction(notify);

	useEffect(() => {
		setAccount(null);
		setCostCenter("");
		setRemarks(row.verwendungszweck || "");
		setWertstellungsdatum(row.buchungstag || "");
		setSplitMode(false);
		setSplits([
			{ id: 1, account: null, costCenter: "", amount: Math.abs(Number(row.betrag) || 0).toFixed(2) },
		]);
	}, [row.id, row.betrag, row.buchungstag, row.verwendungszweck]);

	useEffect(() => {
		let alive = true;
		api.getExpectedCostCenter(docname, row.id)
			.then((d) => {
				if (alive && d && d.cost_center) {
					setCostCenter(d.cost_center);
					setSplits((prev) => prev.map((s) => ({ ...s, costCenter: s.costCenter || d.cost_center })));
				}
			})
			.catch(() => {});
		return () => { alive = false; };
	}, [docname, row.id]);

	const targetAmount = Math.abs(Number(row.betrag) || 0);
	const parseAmount = (value) => {
		const raw = String(value || "").trim();
		const normalized = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
		const n = Number(normalized);
		return Number.isFinite(n) ? n : 0;
	};
	const splitTotal = splits.reduce((sum, s) => sum + parseAmount(s.amount), 0);
	const splitDiff = Math.round((targetAmount - splitTotal) * 100) / 100;
	const splitReady = splits.length > 0 && splits.every((s) => s.account && parseAmount(s.amount) > 0) && Math.abs(splitDiff) <= 0.01;
	const updateSplit = (id, patch) => setSplits((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
	const addSplit = () => {
		setSplits((prev) => [
			...prev,
			{ id: Date.now(), account: null, costCenter: costCenter || "", amount: Math.max(splitDiff, 0).toFixed(2) },
		]);
	};
	const removeSplit = (id) => setSplits((prev) => (prev.length <= 1 ? prev : prev.filter((s) => s.id !== id)));

	const book = () => {
		if (splitMode && !splitReady) {
			if (Math.abs(splitDiff) > 0.01) return notify("error", "Die Split-Summe muss dem Bankbetrag entsprechen.");
			return notify("error", "Bitte je Split-Zeile Konto und Betrag angeben.");
		}
		if (!splitMode && !account) return notify("error", "Bitte ein Gegenkonto wählen.");
		run(
			() => api.createJournalEntry(docname, row.id, {
				account: splitMode ? undefined : account.value,
				costCenter: splitMode ? undefined : costCenter || undefined,
				remarks,
				wertstellungsdatum,
				splits: splitMode ? splits.map((s) => ({
					account: s.account.value,
					cost_center: s.costCenter || undefined,
					amount: parseAmount(s.amount),
				})) : undefined,
			}),
			{ success: "Buchungssatz erstellt und abgeglichen." }
		).then((r) => r && r.ok !== false && onActionDone());
	};

	return (
		<div>
			<div className="seg journal-mode" role="tablist">
				<button className={`seg-btn ${!splitMode ? "active" : ""}`} onClick={() => setSplitMode(false)}>
					Ein Konto
				</button>
				<button className={`seg-btn ${splitMode ? "active" : ""}`} onClick={() => setSplitMode(true)}>
					Aufteilen
				</button>
			</div>

			{!splitMode ? (
				<>
					<div className="field-label" style={{ marginTop: 10 }}>Gegenkonto</div>
					{account ? (
						<div className="picked">
							<span>{account.value}</span>
							<button className="btn sm subtle" onClick={() => setAccount(null)}><Icon name="x" /></button>
						</div>
					) : (
						<LinkSearch placeholder="Konto suchen (z.B. 4970)…" fetcher={api.searchAccounts} onPick={setAccount} />
					)}
					<div className="field-label" style={{ marginTop: 10 }}>Kostenstelle</div>
					<input className="text-input" value={costCenter} placeholder="(optional)" onChange={(e) => setCostCenter(e.target.value)} />
				</>
			) : (
				<div className="journal-splits">
					<div className={`split-summary ${Math.abs(splitDiff) <= 0.01 ? "ok" : "bad"}`}>
						<span>Ziel <strong>{fmtEUR(targetAmount)}</strong></span>
						<span>Split <strong>{fmtEUR(splitTotal)}</strong></span>
						<span>Rest <strong>{fmtEUR(splitDiff)}</strong></span>
					</div>
					{splits.map((s, idx) => (
						<div className="split-row" key={s.id}>
							<div className="split-row-head">
								<span>Zeile {idx + 1}</span>
								<button className="btn sm subtle" onClick={() => removeSplit(s.id)} disabled={splits.length <= 1}>
									<Icon name="x" />
								</button>
							</div>
							<div className="field-label">Konto</div>
							{s.account ? (
								<div className="picked">
									<span>{s.account.value}</span>
									<button className="btn sm subtle" onClick={() => updateSplit(s.id, { account: null })}><Icon name="x" /></button>
								</div>
							) : (
								<LinkSearch placeholder="Konto suchen…" fetcher={api.searchAccounts} onPick={(item) => updateSplit(s.id, { account: item })} />
							)}
							<div className="split-row-grid">
								<div>
									<div className="field-label">Betrag</div>
									<input className="text-input amount-input" value={s.amount} onChange={(e) => updateSplit(s.id, { amount: e.target.value })} />
								</div>
								<div>
									<div className="field-label">Kostenstelle</div>
									<input className="text-input" value={s.costCenter} placeholder="(optional)" onChange={(e) => updateSplit(s.id, { costCenter: e.target.value })} />
								</div>
							</div>
						</div>
					))}
					<button className="btn sm" onClick={addSplit}>
						<Icon name="plus" /> Zeile hinzufügen
					</button>
				</div>
			)}
			<div className="field-label" style={{ marginTop: 10 }}>Wertstellungsdatum</div>
			<input
				className="text-input"
				type="date"
				value={wertstellungsdatum}
				onChange={(e) => setWertstellungsdatum(e.target.value)}
			/>
			<div className="field-label" style={{ marginTop: 10 }}>Bemerkung</div>
			<input className="text-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
			<button className="btn primary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} onClick={book} disabled={busy}>
				{busy ? <Spinner /> : <Icon name="check" />} Buchungssatz erstellen
			</button>
		</div>
	);
}

// ───────────────────────── Phase 3: Vorauszahlung ───────────────────────────

function StandalonePayment({ docname, row, onActionDone, notify }) {
	const [remarks, setRemarks] = useState(row.verwendungszweck || "");
	const [busy, run] = useAction(notify);
	const book = () =>
		run(() => api.createStandalonePayment(docname, row.id, remarks), {
			success: "Vorauszahlung (unallocated) gebucht.",
		}).then((r) => r && r.ok !== false && onActionDone());
	return (
		<div>
			<div className="hint" style={{ marginBottom: 10 }}>
				Bucht den vollen Betrag {fmtEUR(Math.abs(row.betrag))} als unverrechnete Zahlung auf
				{row.party ? ` ${row.party}` : " die Partei"}. Verrechnung mit einer Rechnung später möglich.
			</div>
			<div className="field-label">Bemerkung</div>
			<input className="text-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
			<button className="btn primary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} onClick={book} disabled={busy}>
				{busy ? <Spinner /> : <Icon name="check" />} Vorauszahlung buchen
			</button>
		</div>
	);
}

// ───────────────────────── Phase 3: Interne Umbuchung ──────────────────────

function InternalTransferPayment({ docname, row, onActionDone, notify }) {
	const [bankAccount, setBankAccount] = useState(null);
	const [remarks, setRemarks] = useState(row.verwendungszweck || "");
	const [busy, run] = useAction(notify);
	const isOut = Number(row.betrag) < 0;

	useEffect(() => {
		setBankAccount(null);
		setRemarks(row.verwendungszweck || "");
	}, [row.id, row.verwendungszweck]);

	const book = () => {
		if (!bankAccount) return notify("error", "Bitte das Gegen-Bankkonto wählen.");
		run(() => api.createInternalTransfer(docname, row.id, bankAccount.value, remarks), {
			success: "Interne Umbuchung gebucht und abgeglichen.",
		}).then((r) => r && r.ok !== false && onActionDone());
	};

	return (
		<div>
			<div className="hint" style={{ marginBottom: 10 }}>
				Bucht {fmtEUR(Math.abs(row.betrag))} als internen Transfer
				{isOut ? " auf das gewählte Ziel-Bankkonto." : " vom gewählten Quell-Bankkonto."}
			</div>
			<div className="field-label">{isOut ? "Ziel-Bankkonto" : "Quell-Bankkonto"}</div>
			{bankAccount ? (
				<div className="picked">
					<span>{bankAccount.label || bankAccount.value}</span>
					<button className="btn sm subtle" onClick={() => setBankAccount(null)}><Icon name="x" /></button>
				</div>
			) : (
				<LinkSearch placeholder="Bankkonto suchen…" fetcher={api.listBankAccounts} onPick={setBankAccount} />
			)}
			<div className="field-label" style={{ marginTop: 10 }}>Bemerkung</div>
			<input className="text-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
			<button className="btn primary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} onClick={book} disabled={busy}>
				{busy ? <Spinner /> : <Icon name="check" />} Umbuchung buchen
			</button>
		</div>
	);
}

// ───────────────────────── Phase 3: Abschlagsplan ───────────────────────────

function AbschlagMatch({ docname, row, onActionDone, notify }) {
	const [cands, setCands] = useState(null);
	const [loading, setLoading] = useState(true);
	const [busy, run] = useAction(notify);

	useEffect(() => {
		let alive = true;
		setLoading(true);
		api.getAbschlagsplanCandidates(docname, row.id)
			.then((d) => alive && setCands(d.candidates || []))
			.catch((e) => alive && notify("error", e.message))
			.finally(() => alive && setLoading(false));
		return () => { alive = false; };
	}, [docname, row.id, notify]);

	const assign = (c) =>
		run(() => api.assignAbschlagsplan(docname, row.id, c.row_name), {
			success: "Abschlag zugeordnet und gebucht.",
		}).then((r) => r && r.ok !== false && onActionDone());

	if (loading) return <div className="panel-loading"><Spinner size={18} /> Abschlagspläne laden…</div>;
	if (!cands || !cands.length) return <div className="hint">Keine passende offene Abschlagsplan-Zeile gefunden.</div>;

	return (
		<div>
			{cands.map((c) => (
				<div key={c.row_name} className="invoice-card alt">
					<div className="row1">
						<div>
							<div className="doc-id">{c.bezeichnung || c.zahlungsplan}</div>
							<div className="ref">Fällig {fmtDate(c.faelligkeitsdatum)}{c.immobilie ? ` · ${c.immobilie}` : ""}</div>
						</div>
						<div className="amount">{fmtEUR(c.betrag)}</div>
					</div>
					<button className="btn primary sm" style={{ width: "100%", justifyContent: "center", marginTop: 8 }} onClick={() => assign(c)} disabled={busy}>
						{busy ? <Spinner /> : <Icon name="check" />} Diesen Abschlag zuordnen
					</button>
				</div>
			))}
		</div>
	);
}

// ───────────────────────── Phase 3: Kreditrate ──────────────────────────────

function KreditMatch({ docname, row, onActionDone, notify }) {
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(true);
	const [busy, run] = useAction(notify);

	useEffect(() => {
		let alive = true;
		setLoading(true);
		api.getOpenKreditraten(docname, row.id)
			.then((d) => alive && setData(d))
			.catch((e) => alive && notify("error", e.message))
			.finally(() => alive && setLoading(false));
		return () => { alive = false; };
	}, [docname, row.id, notify]);

	const assign = (c) =>
		run(() => api.assignKreditrate(docname, row.id, c.kreditvertrag, c.rate_name || c.name), {
			success: "Kreditrate gebucht.",
		}).then((r) => r && r.ok !== false && onActionDone());

	const fromStatement = () =>
		run(() => api.bookKreditrateFromStatement(docname, row.id), {
			success: "Kreditrate aus Kontoauszug gebucht.",
		}).then((r) => r && r.ok !== false && onActionDone());

	if (loading) return <div className="panel-loading"><Spinner size={18} /> Kreditraten laden…</div>;
	const cands = (data && data.candidates) || [];
	return (
		<div>
			{cands.length === 0 && <div className="hint">Keine offene Kreditrate gefunden.</div>}
			{cands.map((c, i) => (
				<div key={(c.kreditvertrag || "") + (c.rate_name || c.name || i)} className="invoice-card alt">
					<div className="row1">
						<div>
							<div className="doc-id">{c.kreditvertrag || c.label || "Kreditrate"}</div>
							<div className="ref">{c.faelligkeitsdatum ? `Fällig ${fmtDate(c.faelligkeitsdatum)}` : (c.label || "")}</div>
						</div>
						{c.betrag != null && <div className="amount">{fmtEUR(c.betrag)}</div>}
					</div>
					<button className="btn primary sm" style={{ width: "100%", justifyContent: "center", marginTop: 8 }} onClick={() => assign(c)} disabled={busy}>
						{busy ? <Spinner /> : <Icon name="check" />} Diese Rate buchen
					</button>
				</div>
			))}
			{data && data.can_create_from_statement && (
				<button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 8 }} onClick={fromStatement} disabled={busy}>
					{busy ? <Spinner /> : <Icon name="bolt" />} Rate aus Kontoauszug anlegen &amp; buchen
				</button>
			)}
		</div>
	);
}

// ───────────────────────── Phase 4: gebucht ─────────────────────────────────

function DoneView({ row }) {
	return (
		<div className="match-section">
			<div className="sec-label">Verarbeitung abgeschlossen</div>
			{row.autoMatchMessage && <div className="hint" style={{ marginBottom: 10 }}>{row.autoMatchMessage}</div>}
			{row.bankTransaction && (
				<button className="assign-row done-row" onClick={() => api.openDoc("Bank Transaction", row.bankTransaction)}>
					<span className="lbl">Bank-Tx</span>
					<span className="val mono">{row.bankTransaction}</span>
					<Icon name="link" />
				</button>
			)}
			{row.paymentEntry && (
				<button className="assign-row done-row" style={{ marginTop: 6 }} onClick={() => api.openDoc("Payment Entry", row.paymentEntry)}>
					<span className="lbl">Payment</span>
					<span className="val mono">{row.paymentEntry}</span>
					<Icon name="link" />
				</button>
			)}
			{row.journalEntry && (
				<button className="assign-row done-row" style={{ marginTop: 6 }} onClick={() => api.openDoc("Journal Entry", row.journalEntry)}>
					<span className="lbl">Buchung</span>
					<span className="val mono">{row.journalEntry}</span>
					<Icon name="link" />
				</button>
			)}
		</div>
	);
}

function ErrorView({ row }) {
	return (
		<div className="match-section">
			<div className="sec-label">Zeile fehlerhaft</div>
			<div className="reset-warning">
				<Icon name="info" /> {row.error || row.autoMatchMessage || "Diese Zeile kann erst verarbeitet werden, wenn der Importfehler behoben ist."}
			</div>
		</div>
	);
}

// ───────────────────────── Phase 3 Container (Modus-Wahl) ────────────────────

function BookingActions({ docname, row, onActionDone, notify }) {
	const isOut = Number(row.betrag) < 0;
	const hasParty = !!row.party;
	const modes = useMemo(() => {
		const m = [];
		if (hasParty && (row.partyTyp === "Customer" || row.partyTyp === "Supplier"))
			m.push({ id: "invoice", lbl: "Rechnung" });
		if (isOut && row.partyTyp === "Supplier") m.push({ id: "split", lbl: "Aufteilen" });
		if (isOut && row.partyTyp === "Supplier") m.push({ id: "abschlag", lbl: "Abschlag" });
		if (isOut) m.push({ id: "kredit", lbl: "Kreditrate" });
		if (hasParty) m.push({ id: "payment", lbl: "Vorauszahlung" });
		if (!hasParty) m.push({ id: "transfer", lbl: "Umbuchung" });
		m.push({ id: "journal", lbl: "Buchungssatz" });
		return m;
	}, [isOut, hasParty, row.partyTyp]);

	// Smarter Default: pro Zeile neu inferieren.
	// Deps spiegeln die Felder, die inferBestMode tatsächlich liest — damit ein
	// Refresh derselben row (gleiche row.id) mit aktualisiertem autoMatch oder
	// Verwendungszweck die Empfehlung nicht stale lässt.
	const reco = useMemo(
		() => inferBestMode(row, modes),
		[row.id, row.autoMatch?.rechnungId, row.verwendungszweck, row.auftraggeber, modes]
	);
	const [mode, setMode] = useState(reco.id);
	// Mode-Reset nur bei Zeilenwechsel (row.id) — auf derselben Zeile bleibt
	// die manuelle User-Auswahl bestehen, selbst wenn sich reco nachträglich
	// noch ändert.
	useEffect(() => { setMode(reco.id); }, [row.id]); // eslint-disable-line

	const recoLabel = modes.find((m) => m.id === reco.id)?.lbl;
	const onReco = mode === reco.id;

	return (
		<div className="match-section">
			<div className="sec-label">Beleg zuordnen</div>

			{/* Empfehlungs-Karte: erklärt, warum dieser Modus vorgewählt ist */}
			{reco.reason && (
				<div className={`reco-card ${onReco ? "active" : "muted"}`}>
					<div className="reco-tag">
						{onReco ? "Empfohlen" : "Empfehlung war"} · {recoLabel}
					</div>
					<div className="reco-reason">{reco.reason}</div>
					{!onReco && (
						<button className="reco-revert" onClick={() => setMode(reco.id)}>
							<Icon name="refresh" size={11} /> Wieder vorschlagen
						</button>
					)}
				</div>
			)}

			<div className="seg" role="tablist" style={{ marginBottom: 12 }}>
				{modes.map((m) => (
					<button
						key={m.id}
						className={`seg-btn ${mode === m.id ? "active" : ""} ${m.id === reco.id && reco.reason ? "is-reco" : ""}`}
						onClick={() => setMode(m.id)}
					>
						{m.lbl}
					</button>
				))}
			</div>
			{mode === "invoice" && <InvoiceMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "split" && <SplitPaymentMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "abschlag" && <AbschlagMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "kredit" && <KreditMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "payment" && <StandalonePayment docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "transfer" && <InternalTransferPayment docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "journal" && <JournalEntryForm docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
		</div>
	);
}

// ───────────────────────── Panel-Wurzel ─────────────────────────────────────

export function MatchPanel({ docname, row, onActionDone, notify }) {
	const [partyDialogOpen, setPartyDialogOpen] = useState(false);
	const [resetDialogMode, setResetDialogMode] = useState(null);
	const [resetBusy, runReset] = useAction(notify);

	if (!row) {
		return (
			<div className="match-panel">
				<div className="match-empty">
					<div className="big">⌖</div>
					<div className="ttl">Keine Zeile ausgewählt</div>
					<div className="sub">Klicke links auf eine Bankzeile, um Aktionen zu sehen.</div>
				</div>
			</div>
		);
	}

	const isOut = Number(row.betrag) < 0;
	const phase = row.phase || 3;
	const partyLabel = partyDisplayLabel(row);
	const roleLabel = partyTypeLabel(row.partyTyp);
	const hasVoucher = Boolean(row.paymentEntry || row.journalEntry || row.paymentDocument);
	const canResetRow = Boolean(row.party || row.partyTyp || row.bankTransaction || row.paymentEntry || row.journalEntry || row.paymentDocument);
	const resetBooking = () => {
		if (!hasVoucher || resetBusy) return;
		runReset(() => api.resetRowBooking(docname, row.id), {
			success: "Beleg gelöst.",
		}).then((res) => {
			if (res && res.ok !== false) {
				setResetDialogMode(null);
				onActionDone({ advance: false });
			}
		});
	};
	const resetRow = () => {
		if (!canResetRow || resetBusy) return;
		runReset(() => api.resetRowProcessing(docname, row.id), {
			success: "Zeile zurückgesetzt.",
		}).then((res) => {
			if (res && res.ok !== false) {
				setResetDialogMode(null);
				onActionDone({ advance: false });
			}
		});
	};

	return (
		<div className="match-panel">
			<div className="match-head">
				<div className="row-meta">
					<span>{fmtDate(row.buchungstag)}</span>
					<span>·</span>
					<span>{isOut ? "Ausgang" : "Eingang"}</span>
				</div>
				<div className={`amount-big ${isOut ? "out" : "in"}`}>{fmtEUR(row.betrag)}</div>
				<div className={`bank-tx-ref ${row.bankTransaction ? "has-link" : "missing"}`}>
					<span>Bank-Transaktion</span>
					{row.bankTransaction ? (
						<button className="link-btn" onClick={() => api.openDoc("Bank Transaction", row.bankTransaction)}>
							{row.bankTransaction}
						</button>
					) : (
						<strong>fehlt</strong>
					)}
				</div>
				<div className="party-line with-action">
					<span>
						{row.party ? (
							<button className="party-link detail-party-link" onClick={() => api.openDoc(row.partyTyp, row.party)}>
								{row.party}{roleLabel ? ` · ${roleLabel}` : ""}
							</button>
						) : partyLabel}
					</span>
					<button className="btn subtle sm party-edit-btn" onClick={() => setPartyDialogOpen(true)}>
						<Icon name="settings" /> Partei ändern
					</button>
				</div>
				{canResetRow && (
					<div className="row-action-buttons">
						{hasVoucher && (
							<button className="btn subtle sm" onClick={() => setResetDialogMode("booking")} disabled={resetBusy}>
								{resetBusy ? <Spinner /> : <Icon name="x" />} Beleg lösen
							</button>
						)}
						<button className="btn danger sm" onClick={() => setResetDialogMode("row")} disabled={resetBusy}>
							{resetBusy ? <Spinner /> : <Icon name="trash" />} Zeile zurücksetzen
						</button>
					</div>
				)}
				<div className="zweck">{row.verwendungszweck}</div>
				{row.iban && <div className="iban-line">{fmtIban(row.iban)}</div>}
				<AuditTrail row={row} />
			</div>

			<div className="match-body">
				{row.rowStatus === "error" && <ErrorView row={row} />}
				{row.rowStatus !== "error" && phase === 1 && (
					<PartyAssign docname={docname} row={row} onActionDone={onActionDone} notify={notify} />
				)}
				{row.rowStatus !== "error" && phase === 3 && <BookingActions docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
				{row.rowStatus !== "error" && phase === 4 && <DoneView row={row} />}
			</div>
			{partyDialogOpen && (
				<PartyChangeDialog
					docname={docname}
					row={row}
					onClose={() => setPartyDialogOpen(false)}
					onActionDone={onActionDone}
					notify={notify}
				/>
			)}
			{resetDialogMode && (
				<ResetRowDialog
					row={row}
					mode={resetDialogMode}
					busy={resetBusy}
					onClose={() => setResetDialogMode(null)}
					onConfirm={resetDialogMode === "booking" ? resetBooking : resetRow}
				/>
			)}
		</div>
	);
}
