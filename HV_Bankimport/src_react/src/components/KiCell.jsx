import React from "react";
import { Spinner } from "../helpers.jsx";

export const KiMark = () => <span className="ki-mark">KI</span>;

export function KiConfidence({ value, showScore = false }) {
	if (!value) return null;
	return (
		<span className={`ki-confidence ki-${value.level}`}>
			<span className="ki-meter" aria-hidden="true"><i /><i /><i /></span>
			<span>{value.level}{showScore && value.score != null ? ` · ${Math.round(value.score * 100)} %` : ""}</span>
		</span>
	);
}

export function KiCell({ ki }) {
	let title = "—";
	let detail;
	let statusClass = "";
	if (ki?.state === "running") {
		title = <><Spinner size={11} /> Agent prüft …</>;
	} else if (ki?.state === "none") {
		title = "Kein Vorschlag";
		detail = "Agent unsicher";
	} else if (ki?.state === "proposal") {
		switch (ki.status) {
			case "Pending":
				title = ki.summary;
				detail = <div className="ki-cell-detail">
					<span className="ki-ellipsis" title={ki.kindLabel}>{ki.kindLabel}</span>
					<span aria-hidden="true">·</span><KiConfidence value={ki.confidence} />
				</div>;
				break;
			case "Approved":
				title = "Freigegeben";
				detail = "wartet auf Buchung";
				break;
			case "Stale":
				title = "! Veraltet";
				detail = ki.staleText;
				statusClass = "ki-danger";
				break;
			case "Succeeded":
				title = "✓ übernommen";
				detail = ki.result?.name;
				statusClass = "ki-done";
				break;
			case "Rejected":
				title = "Abgelehnt";
				break;
		}
	}
	return (
		<td className="ki-col">
			<div className={`ki-cell-title ${statusClass}`} title={typeof title === "string" ? title : undefined}>
				{ki && <KiMark />} {title}
			</div>
			{typeof detail === "string" ? <div className="ki-ellipsis ki-muted" title={detail}>{detail}</div> : detail}
		</td>
	);
}
