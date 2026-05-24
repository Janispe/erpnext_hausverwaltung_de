import React, { useEffect } from "react";
import { Icon } from "./Icon.jsx";

// Effektive Input-Pfade auflösen: Override (Vorlage) > Standardpfad (Baustein).
function resolveInputs(baustein, haupt, overrides) {
	const std = (baustein?.standardpfade || []).find((s) => s.startobjekt === haupt);
	const stdMap = std?.mappings || {};
	return (baustein?.inputs || []).map((inp) => {
		const overridePath = (overrides || {})[inp.name];
		const stdPath = stdMap[inp.name];
		const path = overridePath || stdPath || "";
		let status = "ok";
		if (!path) status = "missing";
		else if (overridePath) status = "override";
		return { ...inp, path, status, overridePath };
	});
}

// Aufklappbares Detail-Popover am Baustein-Chip: Inputs (effektiver Pfad + Status),
// Outputs, Knopf zum Pfad-Mapping. Frei positioniert (position: fixed an der Chip-Rect).
export const BausteinPopover = ({
	baustein,
	hauptVerteilObjekt,
	overrides,
	rect,
	onClose,
	onEditMapping,
}) => {
	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "Escape") onClose();
		};
		const onDown = (e) => {
			if (!(e.target.closest && e.target.closest(".baustein-popover"))) onClose();
		};
		window.addEventListener("keydown", onKey);
		const t = setTimeout(() => document.addEventListener("mousedown", onDown), 0);
		return () => {
			window.removeEventListener("keydown", onKey);
			clearTimeout(t);
			document.removeEventListener("mousedown", onDown);
		};
	}, [onClose]);

	if (!baustein) return null;
	const inputs = resolveInputs(baustein, hauptVerteilObjekt, overrides);
	const outputs = baustein.outputs || [];
	const left = Math.max(8, Math.min(rect?.left ?? 100, window.innerWidth - 360));
	const top = (rect?.bottom ?? 100) + 6;

	return (
		<div
			className="baustein-popover"
			style={{ position: "fixed", left, top, zIndex: 320 }}
			onMouseDown={(e) => e.stopPropagation()}
		>
			<div className="bp-header">
				<span className="bp-icon">⧉</span>
				<span className="bp-name">{baustein.title || baustein.name}</span>
				<button className="bp-close" onClick={onClose}>
					<Icon name="x" size={11} />
				</button>
			</div>
			{baustein.description && <div className="bp-desc">{baustein.description}</div>}

			{inputs.length > 0 && (
				<div className="bp-section">
					<div className="bp-section-label">Inputs · {inputs.length}</div>
					<div className="bp-ports">
						{inputs.map((inp, i) => (
							<div className={`bp-port bp-port-${inp.status}`} key={i}>
								<span className="port-pin">●</span>
								<span className="port-label">{inp.label || inp.name}</span>
								<span className="port-type">{inp.reference_doctype || inp.type}</span>
								{inp.path ? (
									<code className="bp-port-path">{inp.path}</code>
								) : (
									<code className="bp-port-path" style={{ color: "var(--danger)" }}>kein Pfad</code>
								)}
							</div>
						))}
					</div>
				</div>
			)}

			{outputs.length > 0 && (
				<div className="bp-section">
					<div className="bp-section-label">Outputs · {outputs.length}</div>
					<div className="bp-ports">
						{outputs.map((out, i) => (
							<div className="bp-port bp-port-out" key={i}>
								<span className="port-pin">●</span>
								<span className="port-label">{out.label || out.name}</span>
								<span className="port-type">{out.reference_doctype || out.type}</span>
							</div>
						))}
					</div>
				</div>
			)}

			{(inputs.length > 0 || outputs.length > 0) && (
				<button className="bp-mapping-btn" onClick={onEditMapping}>
					<Icon name="branch" size={11} /> Pfad-Mapping bearbeiten
				</button>
			)}
			{inputs.length === 0 && outputs.length === 0 && (
				<div className="bp-desc" style={{ padding: "4px 0" }}>Keine Inputs/Outputs.</div>
			)}
		</div>
	);
};
