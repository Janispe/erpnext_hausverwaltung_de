import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";

// Popover zum Editieren eines {% ... %}-Tokens (Jinja-Block/-Inline).
// Loest das alte window.prompt() ab: Inline-Editierung mit Live-Validation,
// Speichern/Abbrechen-Buttons, ESC schliesst, Enter speichert wenn gueltig,
// Outside-Click verwirft.
//
// Aufruf: extensions.js dispatcht ``hv-jinja-token-popover`` mit
//   { token, rect, save(newToken), kind } im detail.
export const JinjaTokenPopover = ({ token, rect, kind, onSave, onClose }) => {
	const [value, setValue] = useState(token || "");
	const inputRef = useRef(null);

	useEffect(() => {
		setValue(token || "");
		// Auto-Fokus + Selektion fuer schnelles Editieren.
		setTimeout(() => {
			inputRef.current?.focus();
			inputRef.current?.select();
		}, 0);
	}, [token]);

	useEffect(() => {
		const mountedAt = Date.now();
		const onKey = (e) => {
			if (e.key === "Escape") onClose();
		};
		const onDown = (e) => {
			if (Date.now() - mountedAt < 50) return;
			if (!(e.target.closest && e.target.closest(".jinja-token-popover"))) onClose();
		};
		window.addEventListener("keydown", onKey);
		document.addEventListener("mousedown", onDown);
		return () => {
			window.removeEventListener("keydown", onKey);
			document.removeEventListener("mousedown", onDown);
		};
	}, [onClose]);

	const trimmed = (value || "").trim();
	// Inline (hvJinjaInline) erlaubt {{ ... }}, Block (hvJinjaBlock) erlaubt {% ... %}.
	// Beide Formen akzeptieren, weil der gleiche Popover beide Knotenarten bedient.
	const isValid = /^\{%[\s\S]*%\}$/.test(trimmed) || /^\{\{[\s\S]*\}\}$/.test(trimmed);

	const left = Math.max(8, Math.min(rect?.left ?? 100, window.innerWidth - 460));
	const top = (rect?.bottom ?? 100) + 6;

	const commitSave = () => {
		if (!isValid) return;
		onSave(trimmed);
		onClose();
	};

	return (
		<div
			className="jinja-token-popover"
			style={{
				position: "fixed",
				left,
				top,
				zIndex: 1000,
				width: 440,
				background: "var(--surface, #fff)",
				border: "1px solid var(--border-strong, #bbb)",
				borderRadius: 8,
				boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
				padding: 12,
				fontFamily: "var(--font-sans)",
				fontSize: 13,
			}}
		>
			<div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
				<Icon name="code" size={13} />
				<strong style={{ flex: 1 }}>Jinja-Ausdruck bearbeiten</strong>
				<button
					type="button"
					onClick={onClose}
					title="Schliessen (ESC)"
					style={{
						background: "none", border: "none", cursor: "pointer",
						fontSize: 14, color: "var(--text-muted, #666)", padding: 0,
					}}
				>
					✕
				</button>
			</div>
			<textarea
				ref={inputRef}
				value={value}
				onChange={(e) => setValue(e.target.value)}
				onKeyDown={(e) => {
					// Enter speichert (Shift+Enter = Newline), ESC handled by global listener.
					if (e.key === "Enter" && !e.shiftKey) {
						e.preventDefault();
						commitSave();
					}
				}}
				rows={2}
				spellCheck={false}
				style={{
					width: "100%",
					boxSizing: "border-box",
					fontFamily: "var(--font-mono, monospace)",
					fontSize: 13,
					padding: "6px 8px",
					border: `1px solid ${isValid ? "var(--border, #ccc)" : "#dc2626"}`,
					borderRadius: 4,
					resize: "vertical",
					outline: "none",
				}}
				placeholder='z.B. {% if mahnstufe == "2" %}'
			/>
			<div style={{ marginTop: 6, fontSize: 11, color: isValid ? "var(--text-muted, #666)" : "#dc2626" }}>
				{isValid
					? "Enter zum Speichern, ESC zum Abbrechen."
					: "Muss mit {% oder {{ beginnen und mit %} oder }} enden."}
			</div>
			<div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end", gap: 6 }}>
				<button
					type="button"
					onClick={onClose}
					style={{
						padding: "4px 10px", fontSize: 12,
						border: "1px solid var(--border, #ccc)", borderRadius: 4,
						background: "var(--surface, #fff)", cursor: "pointer",
					}}
				>
					Abbrechen
				</button>
				<button
					type="button"
					onClick={commitSave}
					disabled={!isValid}
					style={{
						padding: "4px 10px", fontSize: 12,
						border: "1px solid var(--primary, #1f73b7)", borderRadius: 4,
						background: isValid ? "var(--primary, #1f73b7)" : "var(--surface, #fff)",
						color: isValid ? "#fff" : "var(--text-muted, #999)",
						cursor: isValid ? "pointer" : "not-allowed",
					}}
				>
					Speichern
				</button>
			</div>
		</div>
	);
};
