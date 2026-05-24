import React, { useState, useEffect, useMemo } from "react";
import { Icon } from "./Icon.jsx";

// Pfad-Eingabe mit Vorschlägen aus dem Platzhalter-Baum der Vorlage.
// placeholderPaths: [{ path, type, label }] (bare Pfade, z. B. "objekt.wohnung.immobilie").
const PathPicker = ({ value, onChange, expectedDoctype, placeholderPaths }) => {
	const [open, setOpen] = useState(false);
	const q = (value || "").toLowerCase().trim();
	const suggestions = useMemo(() => {
		let list = placeholderPaths || [];
		if (expectedDoctype) {
			const typed = list.filter((p) => p.type === expectedDoctype);
			if (typed.length) list = typed;
		}
		if (q) list = list.filter((p) => p.path.toLowerCase().includes(q));
		return list.slice(0, 12);
	}, [placeholderPaths, expectedDoctype, q]);

	return (
		<div className="path-picker">
			<input
				className="path-picker-input"
				type="text"
				value={value || ""}
				onChange={(e) => onChange(e.target.value)}
				onFocus={() => setOpen(true)}
				onBlur={() => setTimeout(() => setOpen(false), 150)}
				placeholder="z. B. objekt.wohnung.immobilie"
				spellCheck={false}
			/>
			{open && suggestions.length > 0 && (
				<div className="path-picker-suggestions">
					{expectedDoctype && (
						<div className="path-picker-label">Vorschläge (Typ {expectedDoctype}):</div>
					)}
					{suggestions.map((s, i) => (
						<button
							key={i}
							className="path-suggestion"
							onMouseDown={(e) => {
								e.preventDefault();
								onChange(s.path);
								setOpen(false);
							}}
							title={s.path}
						>
							<span className="path-mono">{s.path}</span>
							{s.type && <span className="path-type">{s.type}</span>}
						</button>
					))}
				</div>
			)}
		</div>
	);
};

export const PfadMappingModal = ({
	baustein,
	hauptVerteilObjekt,
	existingOverrides,
	placeholderPaths,
	onClose,
	onSave,
}) => {
	const haupt = hauptVerteilObjekt || "";
	const standardpfad = (baustein?.standardpfade || []).find((s) => s.startobjekt === haupt);
	const stdMappings = standardpfad?.mappings || {};

	const [overrides, setOverrides] = useState(() => {
		const init = {};
		(baustein?.inputs || []).forEach((inp) => {
			init[inp.name] = (existingOverrides && existingOverrides[inp.name]) || "";
		});
		return init;
	});

	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose]);

	if (!baustein) return null;

	const setOverride = (name, path) => setOverrides((o) => ({ ...o, [name]: path }));

	const handleSave = () => {
		// Nur nicht-leere Overrides behalten, die vom Standardpfad abweichen.
		const clean = {};
		Object.entries(overrides).forEach(([name, path]) => {
			const p = (path || "").trim();
			if (p && p !== (stdMappings[name] || "")) clean[name] = p;
		});
		onSave(baustein.name, clean);
		onClose();
	};

	const inputs = baustein.inputs || [];
	const outputs = baustein.outputs || [];

	return (
		<div className="modal-backdrop" onClick={onClose} style={{ zIndex: 300, paddingTop: 80 }}>
			<div className="modal mapping-modal" onClick={(e) => e.stopPropagation()}>
				<div className="modal-header">
					<div>
						<div style={{ fontWeight: 600, fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
							<Icon name="block" size={14} /> Pfad-Mapping: {baustein.title || baustein.name}
						</div>
						<div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
							Startobjekt <strong>{haupt || "—"}</strong> · Standardpfade kommen aus dem Baustein.
							Hier pro Vorlage überschreiben.
						</div>
					</div>
					<button className="btn ghost icon" onClick={onClose}>
						<Icon name="x" size={14} />
					</button>
				</div>

				<div className="modal-body" style={{ padding: 0 }}>
					<div className="mapping-section">
						<div className="mapping-section-title">
							<span>Inputs</span>
							<span className="mapping-section-count">{inputs.length}</span>
						</div>
						{inputs.length === 0 && (
							<div className="empty-hint" style={{ padding: 16 }}>Dieser Baustein hat keine Inputs.</div>
						)}
						{inputs.map((inp, i) => {
							const stdPath = stdMappings[inp.name] || "";
							const overridePath = overrides[inp.name] || "";
							const effective = overridePath || stdPath;
							const status = !effective ? "missing" : overridePath ? "override" : "standard";
							return (
								<div className="mapping-row" key={i}>
									<div className="mapping-row-head">
										<span className="mapping-status-pin" data-status={status} />
										<div className="mapping-input-info">
											<div className="mapping-input-name">
												{inp.label || inp.name}
												<span className="mapping-input-type">{inp.reference_doctype || inp.type}</span>
											</div>
											{inp.desc && <div className="mapping-input-desc">{inp.desc}</div>}
										</div>
									</div>
									<div className="mapping-row-body">
										{stdPath ? (
											<div className="mapping-std-row">
												<span className="mapping-std-label">Standardpfad:</span>
												<code className="mapping-mono">{stdPath}</code>
												{!overridePath && <span className="mapping-active-tag">aktiv</span>}
											</div>
										) : (
											<div className="mapping-std-row mapping-std-missing">
												<span className="mapping-std-label">Standardpfad:</span>
												<em style={{ color: "var(--danger)" }}>keiner — Override nötig</em>
											</div>
										)}
										<div className="mapping-override-row">
											<span className="mapping-std-label">Override (nur diese Vorlage):</span>
											<PathPicker
												value={overridePath}
												onChange={(v) => setOverride(inp.name, v)}
												expectedDoctype={inp.reference_doctype}
												placeholderPaths={placeholderPaths}
											/>
											{overridePath && <span className="mapping-active-tag mapping-active-override">aktiv</span>}
										</div>
									</div>
								</div>
							);
						})}
					</div>

					{outputs.length > 0 && (
						<div className="mapping-section">
							<div className="mapping-section-title">
								<span>Outputs (danach verfügbar)</span>
								<span className="mapping-section-count">{outputs.length}</span>
							</div>
							<div className="mapping-outputs-grid">
								{outputs.map((out, i) => (
									<div className="mapping-output" key={i}>
										<div className="mapping-output-name">
											<span className="port-pin">●</span>
											<code>{`{{ ${out.name} }}`}</code>
										</div>
										<div className="mapping-output-meta">
											<span className="mapping-input-type">{out.reference_doctype || out.type}</span>
											{out.label && <span style={{ color: "var(--text-2)" }}>{out.label}</span>}
										</div>
										{out.desc && <div className="mapping-input-desc">{out.desc}</div>}
									</div>
								))}
							</div>
						</div>
					)}
				</div>

				<div className="modal-footer">
					<button className="btn ghost" onClick={onClose}>Abbrechen</button>
					<button className="btn primary" onClick={handleSave}>
						<Icon name="save" size={13} /> Übernehmen
					</button>
				</div>
			</div>
		</div>
	);
};
