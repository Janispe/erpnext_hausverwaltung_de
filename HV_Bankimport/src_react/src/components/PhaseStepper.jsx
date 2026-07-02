import React from "react";

export function PhaseStepper({ currentPhase, setPhase, phases }) {
	const total = (phases[1] || 0) + (phases[3] || 0) + (phases[4] || 0);
	const steps = [
		{ num: 0, title: "Alle Phasen", desc: "Gesamtübersicht", cnt: total },
		{ num: 1, title: "Parteien zuordnen", desc: "IBAN → Mieter / Lieferant", cnt: phases[1] || 0 },
		{ num: 3, title: "Belege zuordnen", desc: "Rechnungen matchen", cnt: phases[3] || 0 },
		{ num: 4, title: "Gebucht", desc: "Vollständig verarbeitet", cnt: phases[4] || 0 },
	];
	return (
		<div className="phase-stepper">
			{steps.map((s) => {
				const isDone = s.num > 0 && currentPhase !== 0 && currentPhase > s.num;
				const isActive = currentPhase === s.num;
				return (
					<button
						key={s.num}
						className={`phase-step ${isDone ? "done" : ""} ${isActive ? "active" : ""} ${s.num === 0 ? "all-phases" : ""}`}
						onClick={() => setPhase(s.num)}
					>
						<div className="num">{s.num === 0 ? "∗" : isDone ? "✓" : s.num}</div>
						<div className="meta">
							<div className="title">{s.title}</div>
							<div className="desc">{s.desc}</div>
						</div>
						<div className="count">{s.cnt}</div>
					</button>
				);
			})}
		</div>
	);
}
