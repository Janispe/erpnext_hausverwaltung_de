import React, { useState, useEffect, useMemo, useCallback } from "react";
import { fmtEUR, fmtDate, fmtIban, Icon, Spinner } from "../helpers.jsx";
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

// ───────────────────────── Smart-Default-Inferenz ───────────────────────────
// Liefert für eine Phase-3-Zeile den wahrscheinlich richtigen Modus + Begründung.
// Bezieht sich auf die Modi-IDs aus BookingActions: invoice|abschlag|kredit|payment|journal.

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

function PartyAssign({ docname, row, onActionDone, notify }) {
	const [partyType, setPartyType] = useState(row.betrag < 0 ? "Supplier" : "Customer");
	const [busy, run] = useAction(notify);

	const fetcher = useCallback((txt) => api.searchParties(partyType, txt), [partyType]);

	const assign = (item) =>
		run(() => api.assignParty(docname, row.id, partyType, item.value, row.iban), {
			success: `Partei zugeordnet: ${item.value}`,
		}).then((r) => r && onActionDone());

	const createNew = () =>
		run(() => api.createParty(docname, row.id, partyType, row.auftraggeber), {
			success: "Partei angelegt und zugeordnet.",
		}).then((r) => r && onActionDone());

	return (
		<div className="match-section">
			<div className="sec-label">Partei zuordnen</div>
			<div className="seg" role="tablist" style={{ marginBottom: 10 }}>
				{["Customer", "Supplier"].map((t) => (
					<button
						key={t}
						className={`seg-btn ${partyType === t ? "active" : ""}`}
						onClick={() => setPartyType(t)}
					>
						{t === "Customer" ? "Mieter" : "Lieferant"}
					</button>
				))}
			</div>
			<LinkSearch
				placeholder={`${partyType === "Customer" ? "Mieter" : "Lieferant"} suchen…`}
				fetcher={fetcher}
				onPick={assign}
				autoFocus
				disabled={busy}
			/>
			{row.auftraggeber && (
				<button className="btn sm" style={{ marginTop: 10 }} onClick={createNew} disabled={busy}>
					{busy ? <Spinner /> : <Icon name="plus" />} Neu anlegen aus „{row.auftraggeber}"
				</button>
			)}
			<div className="hint">
				Die Zuordnung verlinkt das Bankkonto (IBAN) mit der Partei und überträgt sie auf alle
				passenden Zeilen.
			</div>
		</div>
	);
}

// ───────────────────────── Phase 2: Bank-Tx erstellen ───────────────────────

function NeedsBankTransaction({ onRunGlobal }) {
	return (
		<div className="match-section">
			<div className="sec-label">Bank-Transaktion fehlt</div>
			<div className="hint" style={{ marginBottom: 10 }}>
				Für diese Zeile wurde noch keine Bank Transaction erzeugt. Das passiert gesammelt für
				alle verprobten Zeilen.
			</div>
			<button className="btn primary" onClick={() => onRunGlobal("create_bank_transactions")}>
				<Icon name="bolt" /> Bank-Transaktionen erstellen
			</button>
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

// ───────────────────────── Phase 3: Buchungssatz ────────────────────────────

function JournalEntryForm({ docname, row, onActionDone, notify }) {
	const [account, setAccount] = useState(null);
	const [costCenter, setCostCenter] = useState("");
	const [remarks, setRemarks] = useState(row.verwendungszweck || "");
	const [busy, run] = useAction(notify);

	useEffect(() => {
		let alive = true;
		api.getExpectedCostCenter(docname, row.id)
			.then((d) => { if (alive && d && d.cost_center) setCostCenter(d.cost_center); })
			.catch(() => {});
		return () => { alive = false; };
	}, [docname, row.id]);

	const book = () => {
		if (!account) return notify("error", "Bitte ein Gegenkonto wählen.");
		run(
			() => api.createJournalEntry(docname, row.id, {
				account: account.value, costCenter: costCenter || undefined, remarks,
			}),
			{ success: "Buchungssatz erstellt und abgeglichen." }
		).then((r) => r && r.ok !== false && onActionDone());
	};

	return (
		<div>
			<div className="field-label">Gegenkonto</div>
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

// ───────────────────────── Phase 3 Container (Modus-Wahl) ────────────────────

function BookingActions({ docname, row, onActionDone, notify }) {
	const isOut = Number(row.betrag) < 0;
	const hasParty = !!row.party;
	const modes = useMemo(() => {
		const m = [];
		if (hasParty && (row.partyTyp === "Customer" || row.partyTyp === "Supplier"))
			m.push({ id: "invoice", lbl: "Rechnung" });
		if (isOut && row.partyTyp === "Supplier") m.push({ id: "abschlag", lbl: "Abschlag" });
		if (isOut) m.push({ id: "kredit", lbl: "Kreditrate" });
		if (hasParty) m.push({ id: "payment", lbl: "Vorauszahlung" });
		m.push({ id: "journal", lbl: "Buchungssatz" });
		return m;
	}, [isOut, hasParty, row.partyTyp]);

	// Smarter Default: pro Zeile neu inferieren
	const reco = useMemo(() => inferBestMode(row, modes), [row.id, modes]);
	const [mode, setMode] = useState(reco.id);
	// Reset bei Zeilenwechsel auf die jeweils empfohlene Mode
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
			{mode === "abschlag" && <AbschlagMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "kredit" && <KreditMatch docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "payment" && <StandalonePayment docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
			{mode === "journal" && <JournalEntryForm docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
		</div>
	);
}

// ───────────────────────── Panel-Wurzel ─────────────────────────────────────

export function MatchPanel({ docname, row, onActionDone, onRunGlobal, notify }) {
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

	return (
		<div className="match-panel">
			<div className="match-head">
				<div className="row-meta">
					<span>{fmtDate(row.buchungstag)}</span>
					<span>·</span>
					<span>{isOut ? "Ausgang" : "Eingang"}</span>
					{row.bankTransaction && (
						<>
							<span>·</span>
							<button className="link-btn" onClick={() => api.openDoc("Bank Transaction", row.bankTransaction)}>
								{row.bankTransaction}
							</button>
						</>
					)}
				</div>
				<div className={`amount-big ${isOut ? "out" : "in"}`}>{fmtEUR(row.betrag)}</div>
				<div className="party-line">{row.party || row.auftraggeber || "unbekannt"}{row.partyTyp ? ` · ${row.partyTyp}` : ""}</div>
				<div className="zweck">{row.verwendungszweck}</div>
				{row.iban && <div className="iban-line">{fmtIban(row.iban)}</div>}
			</div>

			<div className="match-body">
				{phase === 1 && <PartyAssign docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
				{phase === 2 && <NeedsBankTransaction onRunGlobal={onRunGlobal} />}
				{phase === 3 && <BookingActions docname={docname} row={row} onActionDone={onActionDone} notify={notify} />}
				{phase === 4 && <DoneView row={row} />}
			</div>
		</div>
	);
}
