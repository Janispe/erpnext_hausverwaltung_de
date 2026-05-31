import React from "react";
import { fmtEUR, fmtDate, fmtIban, StatusPill, Icon } from "../helpers.jsx";

function TxRow({ row, selected, onSelect }) {
	const isOut = Number(row.betrag) < 0;
	const hasParty = !!row.party;
	return (
		<tr
			className={`${selected ? "selected" : ""} ${row.rowStatus === "done" ? "done" : ""}`}
			onClick={() => onSelect(row.id)}
		>
			<td className="col-date">{fmtDate(row.buchungstag)}</td>
			<td className="col-dir"><span className={`dir-dot ${isOut ? "out" : "in"}`} /></td>
			<td className={`col-amount ${isOut ? "out" : "in"}`}>{fmtEUR(row.betrag)}</td>
			<td className="col-party">
				<div className="party-cell">
					<span className="party-name">
						{hasParty ? row.party : (
							<em style={{ color: "var(--text-faint)" }}>Partei fehlt</em>
						)}
					</span>
					{!hasParty && row.auftraggeber && (
						<span className="party-meta">Auftraggeber: {row.auftraggeber}</span>
					)}
					{row.iban && <span className="party-meta">{fmtIban(row.iban).slice(0, 17)}…</span>}
				</div>
			</td>
			<td className="col-zweck">
				<span className="verwendung-cell" title={row.verwendungszweck}>{row.verwendungszweck}</span>
			</td>
			<td className="col-status"><StatusPill row={row} /></td>
			<td className="col-action"><Icon name="chev" /></td>
		</tr>
	);
}

export function TxTable({ rows, selectedId, onSelect, filterLabel }) {
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
				<table className="tx-table">
					<thead>
						<tr>
							<th>Buchungstag</th>
							<th></th>
							<th style={{ textAlign: "right" }}>Betrag</th>
							<th>Partei / IBAN</th>
							<th>Verwendungszweck</th>
							<th>Status</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{rows.map((r) => (
							<TxRow key={r.id} row={r} selected={r.id === selectedId} onSelect={onSelect} />
						))}
					</tbody>
				</table>
			)}
		</div>
	);
}
