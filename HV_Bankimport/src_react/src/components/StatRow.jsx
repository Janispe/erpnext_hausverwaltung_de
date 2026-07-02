import React from "react";
import { fmtEUR, fmtDate, fmtIban } from "../helpers.jsx";

export function StatRow({ meta, rowsCount, phases }) {
	const diff = Number(meta.saldoDifferenz) || 0;
	const hasDiff = Math.abs(diff) > 0.01;
	const offen = (phases[1] || 0) + (phases[3] || 0);
	return (
		<div className="stat-row">
			<div className="stat-card bank">
				<div className="label">Bankkonto</div>
				<div className="value">{meta.bankAccount || meta.bankAccountName || "—"}</div>
				<div className="iban">{meta.iban ? fmtIban(meta.iban) : ""}</div>
			</div>
			<div className="stat-card">
				<div className="label">Saldo lt. Bank</div>
				<div className="value">{fmtEUR(meta.saldoLautBank)}</div>
				<div className="sub">per {fmtDate(meta.saldoStichtag)}</div>
			</div>
			<div className="stat-card">
				<div className="label">Saldo lt. ERP</div>
				<div className="value">{fmtEUR(meta.saldoLautERP)}</div>
				<div className="sub">aktueller Buchstand</div>
			</div>
			<div className={`stat-card diff ${hasDiff ? "has-diff" : "zero"}`}>
				<div className="label">Differenz</div>
				<div className="value">{fmtEUR(diff)}</div>
				<div className="sub">{hasDiff ? "noch offen" : "abgeglichen"}</div>
			</div>
			<div className="stat-card">
				<div className="label">Zeilen / offen</div>
				<div className="value">
					{offen}
					<span style={{ color: "var(--text-faint)", fontSize: 14 }}> / {rowsCount}</span>
				</div>
				<div className="sub">{phases[4] || 0} bereits gebucht</div>
			</div>
		</div>
	);
}
