import React from "react";
import { Icon, Spinner } from "../helpers.jsx";

export function TopBar({ meta, onReload, onNewImport, onSwitchImport, busy }) {
	return (
		<div className="topbar">
			<div style={{ display: "flex", alignItems: "center", gap: 14 }}>
				<div className="brand">
					<div className="mark">HV</div>
					<div>
						<h1>Bankimport</h1>
						<div className="crumb">
							Hausverwaltung &nbsp;·&nbsp; {meta.title || meta.name || "—"}
						</div>
					</div>
				</div>
			</div>
			<div className="actions">
				{onSwitchImport && (
					<button className="btn subtle" onClick={onSwitchImport}>
						<Icon name="file" /> Import wechseln
					</button>
				)}
				<button className="btn subtle" onClick={onReload} disabled={busy}>
					{busy ? <Spinner /> : <Icon name="refresh" />} Neu laden
				</button>
				<button className="btn primary" onClick={onNewImport}>
					<Icon name="upload" /> Neuer Import
				</button>
			</div>
		</div>
	);
}
