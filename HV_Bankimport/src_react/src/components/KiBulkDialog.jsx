import React, { useEffect, useRef, useState } from "react";
import * as api from "../api.js";
import { fmtDate, fmtEUR, partyDisplayLabel, rowPhase } from "../helpers.jsx";
import { isOpenKi, kiBindings, kiError } from "../ki.js";
import { KiConfidence, KiMark } from "./KiCell.jsx";

const MAX_BINDINGS = 128;

export function KiBulkDialog({ meta, rows, docname, reload, onClose, notify }) {
	const dialog = useRef(null);
	const [selected, setSelected] = useState([]);
	const [segment, setSegment] = useState("none");
	const [results, setResults] = useState(null);
	const [busy, setBusy] = useState(false);
	const candidates = rows.filter((row) => rowPhase(row) < 4 && isOpenKi(row))
		.map((row) => ({ ...row, bindings: kiBindings(row.ki) }));
	const picked = candidates.filter((row) => selected.includes(row.id));
	const bindingCount = picked.reduce((total, row) => total + row.bindings.length, 0);
	const sum = (direction) => picked.filter((row) => Math.sign(row.betrag) === direction)
		.reduce((total, row) => total + Math.abs(Number(row.betrag)), 0);
	const select = (mode) => {
		setSegment(mode);
		setSelected(candidates.filter((row) => mode === "all" || (mode === "high" && row.ki.confidence?.level === "hoch")).map((row) => row.id));
	};
	useEffect(() => { dialog.current.showModal(); }, []);
	const close = async () => {
		if (busy) return;
		if (results) await reload();
		onClose();
	};
	const submit = async () => {
		if (busy || !picked.length || bindingCount > MAX_BINDINGS) return;
		setBusy(true);
		try {
			const response = await api.kiAcceptMany(docname, picked.map(({ id, bindings }) => ({ row: id, bindings })));
			setResults(response.results);
			setSelected([]);
			setSegment("none");
		} catch (error) {
			notify("error", kiError(error));
			if (Number(error.status) === 409) await reload();
		} finally {
			setBusy(false);
		}
	};
	const booked = results?.filter((result) => result.ok).length || 0;
	const skipped = results?.filter((result) => result.skipped_reason).length || 0;
	const failed = (results?.length || 0) - booked - skipped;
	return (
		<dialog ref={dialog} className="ki-bulk" aria-labelledby="ki-bulk-title" onCancel={(event) => {
			event.preventDefault();
			close();
		}}>
			<header className="ki-bulk-head">
				<div><h2 id="ki-bulk-title"><KiMark /> Vorschläge übernehmen</h2>
					<div className="ki-muted">{meta.title || meta.bankAccount} · {meta.ki.package}</div></div>
				<button className="btn subtle" aria-label="Dialog schließen" disabled={busy} onClick={close}>×</button>
			</header>
			{results ? <>
				<p className="ki-bulk-summary"><strong>{booked} gebucht · {skipped} übersprungen{failed > 0 && ` · ${failed} fehlgeschlagen`}</strong></p>
				<ul className="ki-results">{results.map((result) => {
					const row = rows.find((item) => item.id === result.row);
					return <li key={result.row}><strong>{row?.ki?.summary || result.row}</strong>
						<span>{result.ok ? `✓ ${result.result?.name || "Gebucht"}` : result.skipped_reason || result.error || result.status}</span>
					</li>;
				})}</ul>
				<footer className="ki-actions">
					<button className="btn" onClick={async () => { await reload(); setResults(null); }}>Zurück zur Auswahl</button>
					<button className="btn primary" onClick={close}>Schließen</button>
				</footer>
			</> : <>
				<div className="ki-bulk-selection">
					<div className="seg" role="group" aria-label="Sammelauswahl">
						{[["high", "Hohe Sicherheit"], ["all", "Alle"], ["none", "Keine"]].map(([mode, label]) =>
							<button className={`seg-btn ${segment === mode ? "active" : ""}`} key={mode} aria-pressed={segment === mode}
								disabled={busy} onClick={() => select(mode)}>{label}</button>)}
					</div>
					<div aria-live="polite">{picked.length} ausgewählt · Eingang {fmtEUR(sum(1))} · Ausgang {fmtEUR(sum(-1))}</div>
				</div>
				<div className="ki-bulk-table"><table>
					<thead><tr><th></th><th>Datum</th><th>Betrag</th><th>Zeile</th><th>Vorschlag</th><th>Sicherheit</th></tr></thead>
					<tbody>{candidates.map(({ id, buchungstag, betrag, ki, ...row }) => <tr key={id}>
						<td><input type="checkbox" aria-label={ki.summary} checked={selected.includes(id)} disabled={busy}
							onChange={(event) => {
								setSegment(null);
								setSelected(event.target.checked ? [...selected, id] : selected.filter((item) => item !== id));
							}} /></td>
						<td>{fmtDate(buchungstag)}</td><td>{fmtEUR(betrag)}</td><td>{row.party ? partyDisplayLabel(row) : row.auftraggeber || partyDisplayLabel(row)}</td>
						<td><strong>{ki.summary}</strong><div className="ki-muted">{ki.kindLabel}</div></td>
						<td><KiConfidence value={ki.confidence} /></td>
					</tr>)}</tbody>
				</table></div>
				<p>Nicht auswählbar: {meta.ki.counts.Stale || 0} veraltete Vorschläge und {meta.ki.counts.none || 0} Zeilen ohne Vorschlag.</p>
				<p className="ki-note">Jeder Vorschlag wird einzeln für seine Revision freigegeben und danach in Datumsreihenfolge gebucht.
					Bei zwei Schritten erst Partei, dann Buchung. Bei einem Fehler stoppt der Lauf, bereits Gebuchtes bleibt gebucht.</p>
				{bindingCount > MAX_BINDINGS && <p role="alert">Pro Lauf sind höchstens 128 Vorschlagsbindungen erlaubt.</p>}
				<footer className="ki-actions">
					<button className="btn" disabled={busy} onClick={close}>Abbrechen</button>
					<button className="btn primary" disabled={!picked.length || busy || bindingCount > MAX_BINDINGS} onClick={submit}>
						{picked.length} übernehmen und buchen
					</button>
				</footer>
			</>}
		</dialog>
	);
}
