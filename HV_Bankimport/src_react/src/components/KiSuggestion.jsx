import React, { useState } from "react";
import { fmtEUR, fmtDateTime, Spinner } from "../helpers.jsx";
import * as api from "../api.js";
import { kiBindings, kiError } from "../ki.js";
import { DocLink } from "./DocLink.jsx";
import { KiMark, KiConfidence } from "./KiCell.jsx";
import { KiPackageLink } from "./KiBanner.jsx";

const categories = {
	wrong_party: "Falsche Partei", wrong_document: "Falscher Beleg",
	wrong_account: "Anderes Konto", do_not_book: "Nicht buchen", other: "Sonstiges",
};

function Rejection({ busy, onReject, onCancel }) {
	const [category, setCategory] = useState("wrong_party");
	const [reason, setReason] = useState("");
	return (
		<form className="invoice-card suggested ki-rejection" onSubmit={(event) => {
			event.preventDefault();
			if (!busy && reason.trim()) onReject(category, reason.trim());
		}}>
			<fieldset>
				<legend>Was stimmt nicht?</legend>
				<div className="ki-actions">
					{Object.entries(categories).map(([value, text]) => <label className="ki-radio" key={value}>
						<input type="radio" name="ki-category" checked={value === category} onChange={() => setCategory(value)} />{text}
					</label>)}
				</div>
			</fieldset>
			<label className="ki-reason-label">Begründung (Pflicht)
				<textarea value={reason} onChange={(event) => setReason(event.target.value)} required maxLength={1000} rows={3} />
			</label>
			<p className="ki-muted">Geht als Rückmeldung an den Agenten. Die Zeile bleibt offen.</p>
			<div className="ki-actions">
				<button className="btn danger" disabled={busy || !reason.trim()}>Ablehnen</button>
				<button type="button" className="btn" data-ki-key="Escape" disabled={busy} onClick={onCancel}>Abbrechen <kbd>Esc</kbd></button>
			</div>
		</form>
	);
}

function Preview({ ki }) {
	return <>
		<div className="reco-tag">{ki.kindLabel}</div>
		<ol className="ki-steps">
			{ki.steps.map((step, index) => <li key={step.proposal}>
				<span className="ki-step-number" aria-hidden="true">{index + 1}</span>
				<div><div className="ki-step-title">{step.title}{step.status === "Succeeded" && " · ✓ erledigt"}</div>
					<strong>{step.target}</strong><div className="ki-muted">{step.sub}</div>
				</div>
				<span className="amount">{step.amount != null && fmtEUR(step.amount)}</span>
			</li>)}
		</ol>
		{ki.postings?.length > 0 && <table className="ki-postings">
			<caption>Buchung (Vorschau)</caption>
			<thead><tr><th>Konto</th><th>Soll</th><th>Haben</th></tr></thead>
			<tbody>{ki.postings.map((posting, index) => <tr key={index}>
				<td title={posting.account}>{posting.label || posting.account}</td>
				<td>{posting.debit ? fmtEUR(posting.debit) : "—"}</td>
				<td>{posting.credit ? fmtEUR(posting.credit) : "—"}</td>
			</tr>)}</tbody>
		</table>}
		<p className="ki-muted">{ki.effect}</p>
		<div className="conf-row">Sicherheit <KiConfidence value={ki.confidence} showScore /></div>
		<div className="reason">„{ki.rationale}“</div>
		{ki.sources?.length > 0 && <div className="ki-sources">Belege: {ki.sources.map((source) =>
			<DocLink key={`${source.doctype}:${source.name}`} doctype={source.doctype} docname={source.name}>{source.label}</DocLink>
		)}</div>}
	</>;
}

export function KiSuggestion({ meta, docname, row, onActionDone, notify, onAdjust }) {
	const [rejecting, setRejecting] = useState(false);
	const [busy, setBusy] = useState(false);
	const ki = row.ki;
	if (!ki) return null;
	const { status, decision, result } = ki;
	const next = ki.steps?.find((step) => step.status !== "Succeeded") || ki.steps?.at(-1);
	const packageLink = <KiPackageLink packageName={meta.package} proposal={next?.proposal} notify={notify} />;
	const approved = status === "Approved";
	const bookingPrefill = next?.kind === "party" ? ki.steps.find((step) => step.kind !== "party")?.prefill : undefined;
	const act = async (action) => {
		if (busy) return;
		setBusy(true);
		try {
			await action();
		} catch (error) {
			notify("error", kiError(error));
			if (Number(error.status) === 409) await onActionDone({ advance: false, ki: true });
		} finally {
			setBusy(false);
		}
	};
	const accept = () => act(async () => {
		const response = await api.kiAccept(docname, row.id, kiBindings(ki));
		const last = response.results?.at(-1);
		const name = last?.result?.name;
		if (response.ok) {
			const message = { invoice: `${response.results.length > 1 ? "Partei zugeordnet · " : ""}Zahlung gebucht · ${next.kind === "party" ? ki.steps.at(-1).target : next.target} ausgeglichen`,
				journal: `Buchungssatz gebucht · ${name}`, abschlag: `Abschlag gebucht · ${ki.summary}`, kredit: `Kreditrate gebucht · ${ki.summary}`,
				payment: `Vorauszahlung gebucht · ${next.target}` };
			notify("success", message[ki.kind] || (name ? `Zahlung gebucht · ${name}` : "Vorschlag übernommen."));
		} else if (response.status === "Stale") {
			notify("error", "Vorschlag ist veraltet, nichts gebucht.");
		} else {
			const prefix = response.results?.some((step) => step.ok) ? "Partei zugeordnet, Buchung fehlgeschlagen: " : "";
			notify("error", prefix + (last?.error || "Vorschlag konnte nicht gebucht werden."));
		}
		await onActionDone({ advance: response.ok, ki: true });
	});
	const reject = (category, reason) => act(async () => {
		await api.kiReject(docname, row.id, kiBindings(ki)[0], category, reason);
		setRejecting(false);
		await onActionDone({ advance: false, ki: true });
	});
	const requestRevision = () => act(async () => {
		await api.kiRequestRevision(docname, row.id, kiBindings(ki)[0]);
		await onActionDone({ advance: false, ki: true });
	});

	return (
		<section className="match-section ki-section" aria-label="KI-Vorschlag">
			{ki.state === "running" && <div className="ki-note ki-running">
				<KiMark /> <Spinner size={14} /> <strong>Agent prüft diese Zeile …</strong>
				<p>Selbst zuordnen geht jederzeit. Kommt der Vorschlag danach, gilt er als veraltet.</p>
			</div>}
			{ki.state === "none" && <div className="ki-note">
				<KiMark /> <strong>Kein Vorschlag</strong><p><em>„{ki.note}“</em></p>
				<div className="ki-muted">{meta.agent} · {fmtDateTime(meta.submittedAt)}</div>
			</div>}
			{status === "Rejected" && <div className="ki-note">
				<KiMark /> <span className="pill ghost">Abgelehnt</span>
				<p>Abgelehnt von {decision?.by} · {fmtDateTime(decision?.at)}: {decision?.reason}</p>
			</div>}
			{status === "Succeeded" && <div className="ki-note">
				<KiMark /> <span className="pill done">Gebucht</span>
				<p>Freigegeben und gebucht von {result?.by} · {fmtDateTime(result?.at)} · {next?.proposal} · Rev. {next?.revision} · {packageLink}</p>
			</div>}
			{status === "Stale" && <div className="invoice-card ki-stale">
				<div className="ki-section-head"><KiMark /> Vorschlag <span className="pill danger">Veraltet</span></div>
				<p><del>{ki.summary}</del></p><p>{ki.staleText}</p>
				{meta.canAccept && <button className="btn" disabled={busy} onClick={requestRevision}>Neue Revision anfordern</button>}
			</div>}
			{(status === "Pending" || approved) && <>
				<div className="sec-label ki-section-head"><KiMark /> Vorschlag <span className="badge">Rev. {next.revision}</span>
					<span className={`pill ${approved ? "phase3" : "phase2"}`}>{approved ? "Freigegeben" : "Prüfung offen"}</span>
				</div>
				{rejecting && !approved && meta.canAccept ? <Rejection busy={busy} onReject={reject} onCancel={() => setRejecting(false)} /> : <>
					<div className="invoice-card suggested">
						{approved && <p className="ki-muted">Freigegeben von {decision?.by} am {fmtDateTime(decision?.at)}</p>}
						<Preview ki={ki} />
					</div>
					<div className="ki-actions">
						{meta.canAccept && <button className="btn primary" disabled={busy} data-ki-key={approved ? undefined : "Enter"} onClick={accept}>
							{approved ? "Buchen" : ki.steps.length > 1 ? "Beide übernehmen & buchen" : "Übernehmen & buchen"}
							{!approved && <kbd>↵</kbd>}
						</button>}
						<button className="btn" disabled={busy} onClick={() => onAdjust(next.prefill, bookingPrefill)}>Anpassen</button>
						{meta.canAccept && !approved && <button className="btn danger" disabled={busy} data-ki-key="r" onClick={() => setRejecting(true)}>Ablehnen …</button>}
					</div>
					{!meta.canAccept && <p className="ki-muted">Nur Prüfer können Vorschläge übernehmen.</p>}
					<p className="ki-muted">Freigabe und Buchung werden einzeln für Revision {next.revision} protokolliert. {packageLink}</p>
				</>}
			</>}
		</section>
	);
}
