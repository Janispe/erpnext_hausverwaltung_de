import React from "react";
import { Icon } from "../helpers.jsx";

export function Toolbar({ filter, setFilter, search, setSearch, counts }) {
	const filters = [
		{ id: "open", lbl: "Offen", cnt: counts.open },
		{ id: "all", lbl: "Alle", cnt: counts.all },
		{ id: "problem", lbl: "Problemzeilen", cnt: counts.problem },
		{ id: "noparty", lbl: "Ohne Partei", cnt: counts.noparty },
		{ id: "nopay", lbl: "Ohne Zahlung", cnt: counts.nopay },
		{ id: "customer", lbl: "Kunde", cnt: counts.customer },
		{ id: "supplier", lbl: "Lieferant", cnt: counts.supplier },
		{ id: "eigentuemer", lbl: "Eigentümer", cnt: counts.eigentuemer },
	];
	return (
		<div className="toolbar">
			<div className="filters">
				{filters.map((f) => (
					<button
						key={f.id}
						className={`filter-chip ${filter === f.id ? "active" : ""}`}
						onClick={() => setFilter(f.id)}
						disabled={f.cnt === 0 && f.id !== "all"}
					>
						{f.lbl}
						<span className="badge">{f.cnt}</span>
					</button>
				))}
			</div>
			<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
				<div className="search">
					<Icon name="search" size={13} />
					<input
						placeholder="Verwendungszweck, Auftraggeber, IBAN…"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
					/>
				</div>
			</div>
		</div>
	);
}
