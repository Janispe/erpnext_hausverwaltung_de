import React from "react";
import { fmtDateTime, Spinner } from "../helpers.jsx";
import { openProposals } from "../api.js";
import { KiMark } from "./KiCell.jsx";

export function KiPackageLink({ packageName, proposal, notify }) {
	const href = `/app/hv-proposals/${encodeURIComponent(packageName)}`;
	const query = proposal ? `?vorschlag=${encodeURIComponent(proposal)}` : "";
	return <a href={href + query} target="_top" onClick={(event) => {
		if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
		event.preventDefault();
		openProposals(packageName, proposal).catch((error) => notify("error", error.message));
	}}>Im Paket ansehen →</a>;
}

export function KiBanner({ meta, openBulk, notify }) {
	const { ki } = meta;
	const { counts, confidence } = ki;
	const open = (counts.Pending || 0) + (counts.Approved || 0);
	if (ki.running) return <div className="ki-banner"><KiMark /><Spinner size={14} />
		Agent prüft den Auszug … {ki.progress?.done} von {ki.progress?.total} Zeilen
	</div>;
	if (!open && !counts.Stale && !counts.none) return <div className="ki-banner ki-muted">
		<KiMark /> Alle Vorschläge erledigt · {counts.Succeeded || 0} übernommen · {counts.Rejected || 0} abgelehnt
	</div>;
	return (
		<div className="ki-banner">
			<KiMark />
			<div><strong>{open} Vorschläge offen für {meta.offeneBuchungen} offene Zeilen</strong>
				<div className="ki-muted">{ki.agent} · {fmtDateTime(ki.submittedAt)} · {ki.package}</div>
			</div>
			<div className="ki-banner-counts">
				<span className="ki-done">{confidence.hoch || 0} hoch</span>
				<span className="ki-warn">{confidence.mittel || 0} mittel</span>
				<span className="ki-danger">{confidence.niedrig || 0} niedrig</span>
				<span>{counts.Stale || 0} veraltet</span><span>{counts.none || 0} ohne Vorschlag</span>
			</div>
			<KiPackageLink packageName={ki.package} notify={notify} />
			{ki.canAccept && <button className="btn" disabled={!open} onClick={openBulk}>
				Vorschläge übernehmen … <span className="badge">{confidence.hoch || 0}</span>
			</button>}
		</div>
	);
}
