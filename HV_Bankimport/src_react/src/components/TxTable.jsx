import React from "react";
import { fmtEUR, fmtDate, fmtIban, partyDisplayLabel, partyTypeLabel, rowPhase, StatusPill, Icon } from "../helpers.jsx";
import { KiCell, KiPartyMark } from "./KiCell.jsx";
import { DocLink } from "./DocLink.jsx";

function TxRow({ row, selected, onSelect, onFocusRow, showKi }) {
	const isOut = Number(row.betrag) < 0;
	const isDone = rowPhase(row) === 4;
	const hasParty = !!row.party;
	const partyLabel = partyDisplayLabel(row);
	const roleLabel = partyTypeLabel(row.partyTyp);
	return (
		<tr
			className={`${selected ? "selected" : ""} ${isDone ? "done" : ""}`}
			tabIndex={showKi ? 0 : undefined}
			onFocus={showKi ? (event) => {
				if (event.target === event.currentTarget) onFocusRow(row.id);
			} : undefined}
			onClick={() => onSelect(row.id)}
		>
			<td className="col-date">{fmtDate(row.buchungstag)}</td>
			<td className="col-dir"><span className={`dir-dot ${isOut ? "out" : "in"}`} /></td>
			<td className={`col-amount ${isOut ? "out" : "in"}`}>{fmtEUR(row.betrag)}</td>
			<td className="col-party">
				<div className="party-cell">
					<span className="party-name">
						{row.customerPayments?.length ? row.customerPayments.map((item) => (
							<div key={item.payment_entry} className="party-meta"><DocLink doctype="Customer" docname={item.customer}>{item.customerLabel || item.customer}</DocLink> · {fmtEUR(item.amount)}</div>
						)) : hasParty ? (
							<DocLink doctype={row.partyTyp} docname={row.party} className="party-link" title={`${roleLabel || "Partei"} öffnen`}>
								{row.partyLabel || row.party}
							</DocLink>
						) : (
							<em style={{ color: "var(--text-faint)" }}>{partyLabel}</em>
						)}
					</span>
					{!hasParty && row.auftraggeber && (
						<span className="party-meta">Auftraggeber: {row.auftraggeber}</span>
					)}
					{row.iban && <span className="party-meta">{fmtIban(row.iban).slice(0, 17)}…</span>}
				{showKi && <KiPartyMark row={row} />}
				</div>
			</td>
			<td className="col-zweck">
				<span className="verwendung-cell" title={row.verwendungszweck}>{row.verwendungszweck}</span>
			</td>
			{showKi && <KiCell ki={row.ki} />}
			<td className="col-status"><StatusPill row={row} /></td>
			<td className="col-action"><Icon name="chev" /></td>
		</tr>
	);
}

export function TxTable({ rows, selectedId, onSelect, onFocusRow, filterLabel, showKi }) {
	return (
		<div className="tx-card">
			<div className="tx-card-head">
				<div className="title">{filterLabel}</div>
				<div className="count">{rows.length} Zeilen</div>
			</div>
			{rows.length === 0 ? (
				<div className="empty-state">
					<div className="ico"><Icon name="file" size={18} /></div>
					<div className="ttl">Keine Zeilen in diesem Filter</div>
					<div>Wähle einen anderen Filter oder lade einen neuen Auszug.</div>
				</div>
			) : (
				<table className={`tx-table ${showKi ? "ki-table" : ""}`}>
					<thead>
						<tr>
							<th>Buchungstag</th>
							<th></th>
							<th style={{ textAlign: "right" }}>Betrag</th>
							<th>Partei / IBAN</th>
							<th className={showKi ? "ki-purpose" : undefined}>Verwendungszweck</th>
							{showKi && <th className="ki-col">KI-Vorschlag</th>}
							<th>Status</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{rows.map((r) => (
							<TxRow key={r.id} row={r} selected={r.id === selectedId} onSelect={onSelect} onFocusRow={onFocusRow} showKi={showKi} />
						))}
					</tbody>
				</table>
			)}
			{showKi && <div className="ki-keys"><kbd>J</kbd> / <kbd>K</kbd> Nächste / vorherige Zeile · <kbd>↵</kbd> Übernehmen · <kbd>R</kbd> Ablehnen · <kbd>Esc</kbd> Abbrechen</div>}
		</div>
	);
}
