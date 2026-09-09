import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { fmtEUR, fmtDate, Icon, Spinner, allocatableInvoiceAmount } from "../helpers.jsx";
import { LinkSearch } from "./LinkSearch.jsx";
import { DocLink } from "./DocLink.jsx";
import * as api from "../api.js";

export function CustomerSplitDialog({ docname, row, onClose, onActionDone, notify }) {
	const [groups, setGroups] = useState([]);
	const [busy, setBusy] = useState(false);
	const alive = useRef(true);
	useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
	const search = useCallback((txt) => api.searchParties("Customer", txt), []);
	const target = Math.round(Number(row.betrag) * 100);
	const groupTotal = (group) => Object.entries(group.selected).reduce((sum, [name, value]) =>
		sum + Math.round(Number(value) * 100) * Math.sign(Number(group.invoices.find((inv) => inv.name === name)?.outstanding_amount)), 0);
	const allocated = groups.reduce((sum, group) => sum + groupTotal(group), 0);
	const valid = groups.length >= 2 && allocated === target && groups.every((group) =>
		!group.loading && !group.error && Object.keys(group.selected).length > 0 &&
		Object.entries(group.selected).every(([name, value]) => {
			const amount = Number(value);
			return Number.isFinite(amount) && amount > 0 && Math.abs(amount * 100 - Math.round(amount * 100)) < 0.000001 &&
				amount <= allocatableInvoiceAmount(group.invoices.find((inv) => inv.name === name));
		})
	);
	const update = (customer, changes) => setGroups((items) => items.map((group) =>
		group.customer === customer ? { ...group, ...changes } : group
	));
	const add = async (item) => {
		if (busy || groups.some((group) => group.customer === item.value)) return;
		const customer = item.value;
		setGroups((items) => [...items, { customer, invoices: [], selected: {}, loading: true }]);
		try {
			const data = await api.getCustomerSplitInvoices(docname, row.id, customer);
			if (alive.current) update(customer, { ...data, loading: false });
		} catch (error) {
			if (alive.current) update(customer, { loading: false, error: error.message });
		}
	};
	const select = (group, invoice, checked) => {
		const selected = { ...group.selected };
		if (checked) selected[invoice.name] = allocatableInvoiceAmount(invoice);
		else delete selected[invoice.name];
		update(group.customer, { selected });
	};
	const book = async () => {
		if (busy || !valid) return;
		setBusy(true);
		try {
			const result = await api.reconcileCustomerSplit(docname, row.id, groups.map((group) => ({
				customer: group.customer,
				invoices: Object.entries(group.selected).map(([name, value]) => ({ name, allocated_amount: Number(value) })),
			})));
			if (result.ok === false) throw new Error(result.message || "Aufteilung konnte nicht gebucht werden.");
			notify("success", "Belege ausgeglichen und Bankumsatz vollständig abgeglichen.");
			onClose();
			onActionDone({ advance: false });
		} catch (error) {
			notify("error", error.message);
		} finally {
			if (alive.current) setBusy(false);
		}
	};
	return createPortal(
		<div className="modal-backdrop">
			<div className="party-dialog customer-split-dialog" role="dialog" aria-modal="true" aria-label="Auf mehrere Mieter aufteilen">
				<div className="dialog-head">
					<div><div className="dialog-title">Auf mehrere Mieter aufteilen</div><div className="dialog-sub">{fmtDate(row.buchungstag)} · {fmtEUR(row.betrag)}</div></div>
					<button className="btn subtle sm" onClick={onClose} disabled={busy} title="Schließen" aria-label="Schließen"><Icon name="x" /></button>
				</div>
				<LinkSearch placeholder="Mieter hinzufügen" fetcher={search} onPick={add} disabled={busy} autoFocus searchWhenEmpty />
				{groups.map((group) => (
					<section key={group.customer} className="customer-split-group">
						<div className="customer-split-heading">
							<DocLink doctype="Customer" docname={group.customer}>{group.customer}</DocLink>
							<strong>{fmtEUR(groupTotal(group) / 100)}</strong>
							<button className="btn subtle sm" title="Mieter entfernen" aria-label={`Mieter ${group.customer} entfernen`} disabled={busy} onClick={() => setGroups((items) => items.filter((item) => item.customer !== group.customer))}><Icon name="trash" /></button>
						</div>
						{group.contract && <div className="customer-split-contract">{group.contract} · {group.wohnung}</div>}
						{group.loading && <div className="panel-loading"><Spinner /> Belege laden…</div>}
						{group.error && <div role="alert" className="reset-warning">{group.error}</div>}
						{!group.loading && !group.error && !group.invoices.length && <div className="hint">Keine offenen Rechnungen oder Guthaben.</div>}
						{group.invoices.map((invoice) => (
							<div key={invoice.name} className="customer-split-invoice">
								<label><input type="checkbox" checked={group.selected[invoice.name] != null} disabled={busy} onChange={(event) => select(group, invoice, event.target.checked)} /><span>{invoice.name}<small>{Number(invoice.outstanding_amount) < 0 ? "Guthaben" : "Forderung"} · {invoice.remarks || fmtDate(invoice.posting_date)}</small></span></label>
								<span>{fmtEUR(invoice.outstanding_amount)}</span>
								{group.selected[invoice.name] != null && <input className="alloc-input" aria-label={`Teilbetrag ${invoice.name}`} type="number" min="0.01" step="0.01" max={allocatableInvoiceAmount(invoice)} disabled={busy} value={group.selected[invoice.name]} onChange={(event) => update(group.customer, { selected: { ...group.selected, [invoice.name]: event.target.value } })} />}
							</div>
						))}
					</section>
				))}
				<div className="alloc-summary customer-split-summary"><span>Zugewiesen <strong>{fmtEUR(allocated / 100)}</strong></span><span className={allocated === target ? "ok" : "bad"}>Rest <strong>{fmtEUR((target - allocated) / 100)}</strong></span></div>
				<div className="dialog-actions"><button className="btn" onClick={onClose} disabled={busy}>Abbrechen</button><button className="btn primary" disabled={busy || !valid} onClick={book}>{busy ? <Spinner /> : <Icon name="check" />} Aufteilung buchen</button></div>
			</div>
		</div>, document.body
	);
}

export function CustomerPayments({ row }) {
	return <div className="customer-payments">{(row.customerPayments || []).map((item) => (
		<div className="customer-split-group" key={item.customer}>
			<div className="customer-split-heading"><DocLink doctype="Customer" docname={item.customer}>{item.customer}</DocLink><strong>{fmtEUR(item.amount)}</strong></div>
			<div className="customer-split-contract">{item.contract} · {item.wohnung}</div>
			<DocLink doctype={item.journal_entry ? "Journal Entry" : "Payment Entry"} docname={item.journal_entry || item.payment_entry}>{item.journal_entry || item.payment_entry} <Icon name="link" size={12} /></DocLink>
		</div>
	))}</div>;
}
