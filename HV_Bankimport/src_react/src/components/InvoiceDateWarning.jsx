import React from "react";
import { fmtDate, fmtEUR } from "../helpers.jsx";

export function InvoiceDateWarning({ invoice, amount, checked, onChange, disabled }) {
	const review = invoice.after_contract_end_review;
	if (!review) return null;
	return <div className="reset-warning" role="alert">
		<div>{invoice.date_warning}</div>
		<div>{invoice.name} · {review.contract} · {review.wohnung}</div>
		<div>Rechnungsdatum {fmtDate(review.posting_date)} · Vertragsende {fmtDate(review.contract_end)} · Zuordnung {fmtEUR(amount)}</div>
		<label><input type="checkbox" aria-label={`Nachträgliche Abrechnung ${invoice.name} bestätigen`} checked={checked} onChange={(event) => onChange(event.target.checked)} disabled={disabled} /> Ich habe geprüft, dass diese Rechnung eine nachträgliche Abrechnung dieses Mietverhältnisses betrifft, und bestätige diese Zuordnung.</label>
	</div>;
}
