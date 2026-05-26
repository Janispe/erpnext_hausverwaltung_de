import React, { useEffect } from "react";
import { Icon } from "./Icon.jsx";

// Variablentypen, die im Editor als Wert (Text-Input/Checkbox) erfasst werden,
// statt als Doctype-Pfad. Müssen synchron mit dem Backend-Render-Pfad bleiben
// (serienbrief_durchlauf._apply_block_variables: variable_type not in ("Text", "Bool")).
const VALUE_TYPES = new Set(["Text", "Bool"]);

function isDoctypeInput(inp) {
	const t = (inp?.type || "").trim();
	return t && !VALUE_TYPES.has(t);
}

// Effektive Input-Pfade auflösen: Override (Vorlage) > Standardpfad (Baustein).
function resolveInputs(baustein, haupt, overrides) {
	const std = (baustein?.standardpfade || []).find((s) => s.startobjekt === haupt);
	const stdMap = std?.mappings || {};
	return (baustein?.inputs || []).filter(isDoctypeInput).map((inp) => {
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
// Werte (Text/Bool), Outputs, Knopf zum Pfad-Mapping. Frei positioniert.
export const BausteinPopover = ({
	baustein,
	hauptVerteilObjekt,
	overrides,
	values,
	rect,
	onClose,
	onEditMapping,
	onValuesChange,
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
	const valueVars = (baustein.inputs || []).filter((inp) => !isDoctypeInput(inp));
	const outputs = baustein.outputs || [];
	const left = Math.max(8, Math.min(rect?.left ?? 100, window.innerWidth - 360));
	const top = (rect?.bottom ?? 100) + 6;

	const setValue = (name, val) => {
		if (typeof onValuesChange !== "function") return;
		// null/undefined/leerer String → Eintrag entfernen, damit das gespeicherte JSON
		// nicht mit Leereinträgen zumüllt. Bool=false ist KEIN Leerwert.
		const next = { ...(values || {}) };
		if (val === null || val === undefined || val === "") delete next[name];
		else next[name] = val;
		onValuesChange(next);
	};

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

			{valueVars.length > 0 && (
				<div className="bp-section">
					<div className="bp-section-label">Werte · {valueVars.length}</div>
					<div className="bp-values">
						{valueVars.map((v, i) => {
							const cur = (values || {})[v.name];
							const t = (v.type || "").trim();
							return (
								<div className="bp-value-row" key={i}>
									<label className="bp-value-label" title={v.desc || ""}>
										{v.label || v.name}
										<span className="bp-value-type">{t}</span>
									</label>
									{t === "Bool" ? (
										<input
											type="checkbox"
											className="bp-value-checkbox"
											checked={cur === true || cur === "true" || cur === 1 || cur === "1"}
											onChange={(e) => setValue(v.name, e.target.checked)}
										/>
									) : (
										<input
											type="text"
											className="bp-value-input"
											value={cur ?? ""}
											placeholder={v.desc || "Wert eintragen…"}
											onChange={(e) => setValue(v.name, e.target.value)}
										/>
									)}
								</div>
							);
						})}
					</div>
				</div>
			)}

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

			{inputs.length > 0 && (
				<button className="bp-mapping-btn" onClick={onEditMapping}>
					<Icon name="branch" size={11} /> Pfad-Mapping bearbeiten
				</button>
			)}
			{inputs.length === 0 && outputs.length === 0 && valueVars.length === 0 && (
				<div className="bp-desc" style={{ padding: "4px 0" }}>Keine Variablen.</div>
			)}
		</div>
	);
};
