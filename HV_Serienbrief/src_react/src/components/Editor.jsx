import React, { useState, useRef, useEffect, useCallback } from "react";
import { useEditor, EditorContent, BubbleMenu } from "@tiptap/react";
import { Icon } from "./Icon.jsx";
import { PLACEHOLDER_GROUPS, SNIPPETS, TEXT_BAUSTEINE } from "../data.js";
import { buildExtensions } from "../tiptap/extensions.js";
import { decorateForTiptap, serializeToTokens, groupForToken } from "../tiptap/tokens.js";
import { diffTokens } from "../tiptap/validateJinja.js";
import { loadPref, savePref } from "../persist.js";

// Einzel-Token (Platzhalter/Baustein/inline-Jinja) als atomarer Node einfügen (robuster als
// HTML-Parsing). Mehr-Token-Snippets mit Leerzeilen -> decorate + insertContent(HTML).
function insertRawToken(editor, raw) {
	if (!editor || !raw) return;
	const t = raw.trim();
	const isSingle =
		(/^\{\{[\s\S]*\}\}$/.test(t) && t.indexOf("}}") === t.length - 2) ||
		(/^\{%[\s\S]*%\}$/.test(t) && t.indexOf("%}") === t.length - 2);
	let node = null;
	if (isSingle) {
		if (/^\{\{\s*baustein\(/.test(t)) node = { type: "hvBaustein", attrs: { token: t } };
		else if (t.startsWith("{{")) {
			const inner = (/\{\{\s*([\s\S]+?)\s*\}\}/.exec(t) || [])[1] || "";
			// In einer Bedingung: bare Feld-Chip (mieter.anrede) statt {{ }}.
			node = editor.isActive("hvIf")
				? { type: "hvField", attrs: { name: inner, group: groupForToken(inner) } }
				: { type: "hvPlaceholder", attrs: { token: t, group: groupForToken(inner) } };
		} else node = { type: "hvJinjaInline", attrs: { token: t } };
	}
	if (node) editor.chain().focus().insertContent(node).run();
	else editor.chain().focus().insertContent(decorateForTiptap(t)).run();
}

// =========================
// Slash menu (Schnell-Einfügen, mock-basiert wie bisher; Picks gehen über onInsertItem)
// =========================
const SlashMenu = ({ open, x, y, query, onClose, onPick }) => {
	const groups = PLACEHOLDER_GROUPS;
	const snippets = SNIPPETS;
	const bausteine = TEXT_BAUSTEINE;
	const q = (query || "").toLowerCase().trim();
	const matchesPh = groups.flatMap((g) =>
		g.items
			.filter((it) => !q || it.label.toLowerCase().includes(q) || it.token.toLowerCase().includes(q))
			.map((it) => ({ kind: "placeholder", group: g, item: it }))
	);
	const matchesSn = snippets
		.filter((s) => !q || s.label.toLowerCase().includes(q))
		.map((s) => ({ kind: "snippet", item: s }));
	const matchesBs = bausteine
		.filter((b) => !q || b.name.toLowerCase().includes(q))
		.map((b) => ({ kind: "baustein", item: b }));
	const [active, setActive] = useState(0);
	const all = [...matchesPh.slice(0, 8), ...matchesSn, ...matchesBs];
	useEffect(() => {
		setActive(0);
	}, [query]);
	useEffect(() => {
		const onKey = (e) => {
			if (!open) return;
			if (e.key === "Escape") {
				e.preventDefault();
				onClose();
			} else if (e.key === "ArrowDown") {
				e.preventDefault();
				setActive((a) => Math.min(a + 1, all.length - 1));
			} else if (e.key === "ArrowUp") {
				e.preventDefault();
				setActive((a) => Math.max(a - 1, 0));
			} else if (e.key === "Enter") {
				e.preventDefault();
				const sel = all[active];
				if (sel) onPick(sel);
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [open, all, active, onClose, onPick]);
	if (!open) return null;
	return (
		<div className="slash-menu" style={{ left: x, top: y }}>
			<div className="slash-header">Einfügen{query ? ` · "${query}"` : ""}</div>
			<div className="slash-list">
				{matchesPh.length > 0 && <div className="slash-section-label">Platzhalter</div>}
				{matchesPh.slice(0, 8).map((m, i) => (
					<div
						key={`p-${i}`}
						className={`slash-item ${i === active ? "active" : ""}`}
						onMouseEnter={() => setActive(i)}
						onClick={() => onPick(m)}
					>
						<span className="slash-icon">
							<Icon name={m.group.icon} size={13} />
						</span>
						<span className="slash-text">
							<div className="slash-label">{m.item.label}</div>
							<div className="slash-desc">{m.item.token}</div>
						</span>
					</div>
				))}
				{matchesSn.length > 0 && <div className="slash-section-label">Snippets</div>}
				{matchesSn.map((m, i) => {
					const idx = matchesPh.slice(0, 8).length + i;
					return (
						<div
							key={`s-${i}`}
							className={`slash-item ${idx === active ? "active" : ""}`}
							onMouseEnter={() => setActive(idx)}
							onClick={() => onPick(m)}
						>
							<span className="slash-icon">
								<Icon name="branch" size={13} />
							</span>
							<span className="slash-text">
								<div className="slash-label">{m.item.label}</div>
								<div className="slash-desc">{m.item.desc}</div>
							</span>
						</div>
					);
				})}
				{matchesBs.length > 0 && <div className="slash-section-label">Bausteine</div>}
				{matchesBs.map((m, i) => {
					const idx = matchesPh.slice(0, 8).length + matchesSn.length + i;
					return (
						<div
							key={`b-${i}`}
							className={`slash-item ${idx === active ? "active" : ""}`}
							onMouseEnter={() => setActive(idx)}
							onClick={() => onPick(m)}
						>
							<span className="slash-icon">
								<Icon name="block" size={13} />
							</span>
							<span className="slash-text">
								<div className="slash-label">{m.item.name}</div>
								<div className="slash-desc">{m.item.desc}</div>
							</span>
						</div>
					);
				})}
				{all.length === 0 && <div className="empty-hint">Keine Treffer für „{query}".</div>}
			</div>
		</div>
	);
};

// =========================
// Toolbar (TipTap-Chain-Commands + aktive States)
// =========================
const TBtn = ({ on, active, disabled, title, children }) => (
	<button
		className={`tool-btn ${active ? "is-active" : ""}`}
		title={title}
		disabled={disabled}
		onMouseDown={(e) => e.preventDefault()}
		onClick={on}
	>
		{children}
	</button>
);

const EditorToolbar = ({ editor, disabled, onInsert, onImage, showGrid, onToggleGrid }) => {
	const can = !!editor && !disabled;
	const isA = (name, attrs) => !!editor && editor.isActive(name, attrs);
	const chain = () => editor.chain().focus();
	const inTable = isA("table");
	const inIf = isA("hvIf");
	const insertOp = (txt) => chain().insertContent(txt).run();
	const OPS = [
		["=", " == ", "ist gleich"],
		["≠", " != ", "ist ungleich"],
		[">", " > ", "größer als"],
		["<", " < ", "kleiner als"],
		["und", " and ", "und"],
		["oder", " or ", "oder"],
		["nicht", "not ", "nicht / negieren"],
		["enthält", " in ", "enthält / in"],
	];
	const blockValue = isA("heading", { level: 1 })
		? "Überschrift 1"
		: isA("heading", { level: 2 })
			? "Überschrift 2"
			: isA("heading", { level: 3 })
				? "Überschrift 3"
				: "Fließtext";
	return (
		<div className="editor-toolbar">
			<div className="tool-group">
				<select
					className="block-style-select"
					value={blockValue}
					disabled={!can}
					onMouseDown={(e) => e.stopPropagation()}
					onChange={(e) => {
						const v = e.target.value;
						if (v === "Fließtext") chain().setParagraph().run();
						else {
							const level = Number(v.slice(-1));
							chain().toggleHeading({ level }).run();
						}
					}}
				>
					<option>Fließtext</option>
					<option>Überschrift 1</option>
					<option>Überschrift 2</option>
					<option>Überschrift 3</option>
				</select>
				<select
					className="block-style-select"
					title="Schriftgröße"
					value={(editor && editor.getAttributes("textStyle").fontSize) || ""}
					disabled={!can}
					onMouseDown={(e) => e.stopPropagation()}
					onChange={(e) => {
						const v = e.target.value;
						if (v) chain().setFontSize(v).run();
						else chain().unsetFontSize().run();
					}}
				>
					<option value="">Größe</option>
					<option value="10px">10</option>
					<option value="11px">11</option>
					<option value="12px">12</option>
					<option value="14px">14</option>
					<option value="16px">16</option>
					<option value="18px">18</option>
					<option value="20px">20</option>
					<option value="24px">24</option>
				</select>
			</div>
			<div className="tool-group">
				<TBtn title="Fett" active={isA("bold")} disabled={!can} on={() => chain().toggleBold().run()}>
					<Icon name="bold" />
				</TBtn>
				<TBtn title="Kursiv" active={isA("italic")} disabled={!can} on={() => chain().toggleItalic().run()}>
					<Icon name="italic" />
				</TBtn>
				<TBtn title="Unterstrichen" active={isA("underline")} disabled={!can} on={() => chain().toggleUnderline().run()}>
					<Icon name="underline" />
				</TBtn>
				<TBtn title="Hochgestellt" active={isA("superscript")} disabled={!can} on={() => chain().toggleSuperscript().run()}>
					<span style={{ fontSize: 12 }}>x²</span>
				</TBtn>
			</div>
			<div className="tool-group">
				<TBtn title="Links" active={isA({ textAlign: "left" })} disabled={!can} on={() => chain().setTextAlign("left").run()}>
					<Icon name="align-left" />
				</TBtn>
				<TBtn title="Zentriert" active={isA({ textAlign: "center" })} disabled={!can} on={() => chain().setTextAlign("center").run()}>
					<Icon name="align-center" />
				</TBtn>
				<TBtn title="Rechts" active={isA({ textAlign: "right" })} disabled={!can} on={() => chain().setTextAlign("right").run()}>
					<Icon name="align-right" />
				</TBtn>
			</div>
			<div className="tool-group">
				<TBtn title="Liste" active={isA("bulletList")} disabled={!can} on={() => chain().toggleBulletList().run()}>
					<Icon name="list" />
				</TBtn>
				<TBtn title="Nummerierte Liste" active={isA("orderedList")} disabled={!can} on={() => chain().toggleOrderedList().run()}>
					<Icon name="list-ordered" />
				</TBtn>
				<TBtn
					title="Link"
					active={isA("link")}
					disabled={!can}
					on={() => {
						const prev = editor.getAttributes("link").href || "";
						const url = prompt("Link-URL:", prev);
						if (url === null) return;
						if (url === "") chain().unsetLink().run();
						else chain().setLink({ href: url }).run();
					}}
				>
					<Icon name="link" />
				</TBtn>
			</div>
			<div className="tool-group">
				<label className="tool-btn" title="Textfarbe" style={{ position: "relative" }}>
					<Icon name="palette" />
					<input
						type="color"
						disabled={!can}
						onChange={(e) => chain().setColor(e.target.value).run()}
						style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}
					/>
				</label>
				<TBtn title="Hervorheben" active={isA("highlight")} disabled={!can} on={() => chain().toggleHighlight({ color: "#fff2a8" }).run()}>
					<Icon name="highlight" />
				</TBtn>
			</div>
			<div className="tool-group">
				<TBtn title="Tabelle einfügen (2×2) — bearbeiten über das Menü an der Tabelle" disabled={!can} on={() => chain().insertTable({ rows: 2, cols: 2, withHeaderRow: false }).run()}>
					<Icon name="table" />
				</TBtn>
				<TBtn title="Bild einfügen" disabled={!can} on={onImage}>
					<Icon name="image" />
				</TBtn>
				<TBtn
					title={showGrid ? "Tabellen-Hilfslinien ausblenden" : "Tabellen-Hilfslinien einblenden"}
					active={!showGrid}
					on={onToggleGrid}
				>
					<Icon name="grid" />
				</TBtn>
				{inTable && (
					<TBtn
						title="Diese Zeile als Schleife wiederholen ({% for %})"
						active={isA("tableRow", {}) && !!editor.getAttributes("tableRow").loopExpr}
						disabled={!can}
						on={() => {
							const cur = editor.getAttributes("tableRow").loopExpr || "";
							const expr = prompt(
								"Schleifen-Ausdruck (z. B. row in payments) — leer = Schleife entfernen:",
								cur
							);
							if (expr === null) return;
							chain().setRowLoopExpr(expr.trim() || null).run();
						}}
					>
						<Icon name="repeat" />
					</TBtn>
				)}
			</div>
			{inIf && (
				<div className="tool-group op-group" title="Operatoren für die Bedingung">
					{OPS.map(([label, txt, tip]) => (
						<button
							key={label}
							className="tool-btn op-btn"
							title={tip}
							disabled={!can}
							onMouseDown={(e) => e.preventDefault()}
							onClick={() => insertOp(txt)}
						>
							{label}
						</button>
					))}
				</div>
			)}
			<div style={{ flex: 1 }} />
			<div className="tool-group" style={{ borderRight: "none" }}>
				<button className="tool-btn tool-btn-wide primary-tool" onClick={onInsert} title="Einfügen / Slash-Commander" disabled={!can}>
					<Icon name="tag" size={14} />
					<span>Einfügen</span>
					<span className="kbd" style={{ marginLeft: 4 }}>/</span>
				</button>
			</div>
		</div>
	);
};

// Schwebe-Menü für Tabellen (offizielles BubbleMenu-Addon + die in der Table-Extension
// bereits vorhandenen Befehle). Erscheint, sobald der Cursor in einer Tabelle steht.
const TableBubbleMenu = ({ editor }) => {
	if (!editor) return null;
	const run = (fn) => () => fn(editor.chain().focus()).run();
	return (
		<BubbleMenu
			editor={editor}
			pluginKey="hvTableBubble"
			// WICHTIG: @tiptap/react friert shouldShow beim ersten Mount ein (das Plugin-
			// useEffect hängt nicht an shouldShow). Beim Start ist die Vorlage noch leer
			// (canWrite=false), ein eingefrorenes `editable`-Prop bliebe also dauerhaft
			// false und das Menü erschiene nie. Daher live `editor.isEditable` lesen
			// (wird via editor.setEditable(editable) aktuell gehalten).
			shouldShow={({ editor }) => editor.isEditable && editor.isActive("table")}
			tippyOptions={{ placement: "top", maxWidth: "none" }}
		>
			<div className="table-bubble">
				<button title="Spalte rechts einfügen" onClick={run((c) => c.addColumnAfter())}>Sp ＋</button>
				<button title="Spalte löschen" onClick={run((c) => c.deleteColumn())}>Sp －</button>
				<span className="tb-sep" />
				<button title="Zeile darunter einfügen" onClick={run((c) => c.addRowAfter())}>Zeile ＋</button>
				<button title="Zeile löschen" onClick={run((c) => c.deleteRow())}>Zeile －</button>
				<span className="tb-sep" />
				<button title="Kopfzeile an/aus" onClick={run((c) => c.toggleHeaderRow())}>Kopf</button>
				<span className="tb-sep" />
				<button
					title="Rahmen dieser Tabelle im PDF drucken (an/aus)"
					className={editor.getAttributes("table").borders ? "is-active" : ""}
					onClick={() =>
						editor
							.chain()
							.focus()
							.updateAttributes("table", { borders: !editor.getAttributes("table").borders })
							.run()
					}
				>
					Rahmen
				</button>
				<span className="tb-sep" />
				<button className="tb-danger" title="Tabelle löschen" onClick={run((c) => c.deleteTable())}>
					Tabelle ✕
				</button>
			</div>
		</BubbleMenu>
	);
};

// =========================
// Editor (TipTap)
// =========================
export const Editor = ({
	template,
	recipient,
	loading,
	canWrite,
	contentRef,
	onDirty,
	onInsertItem,
	onPickRecipient,
	onMaximizePreview,
	onImageUpload,
	onSafety,
}) => {
	const hasHtml = typeof template.htmlContent === "string";
	const [safety, setSafety] = useState(null); // null = sicher; sonst { lost, added }
	const editable = hasHtml && !!canWrite && !safety;
	const [, force] = useState(0);
	const fileInputRef = useRef(null);
	// Tabellen-Hilfslinien ein/aus (globale Ansichts-Präferenz, gemerkt).
	const [showGrid, setShowGrid] = useState(() => loadPref("tableGrid", true));
	useEffect(() => savePref("tableGrid", showGrid), [showGrid]);

	const editor = useEditor({
		extensions: buildExtensions(),
		editable,
		content: "",
		editorProps: { attributes: { class: "tiptap-surface" } },
		onUpdate: () => onDirty && onDirty(),
		onSelectionUpdate: () => force((n) => n + 1),
		onTransaction: () => force((n) => n + 1),
	});

	// Inhalt laden, wenn sich die Vorlage ändert (decorate -> TipTap). emitUpdate=false,
	// damit Laden nicht als dirty zählt.
	useEffect(() => {
		if (!editor) return;
		const original = template.htmlContent || "";
		editor.commands.setContent(decorateForTiptap(original), false);
		// Token-Erhalt-Check: ging beim Laden ein Token verloren (nicht modellierbare Struktur)?
		const back = serializeToTokens(editor.getHTML());
		const d = diffTokens(original, back);
		const info = d.ok ? null : d;
		setSafety(info);
		onSafety && onSafety(info);
	}, [editor, template.id, template.htmlContent, onSafety]);

	useEffect(() => {
		if (editor) editor.setEditable(editable);
	}, [editor, editable]);

	// contentRef-API für App (getHtml/insertToken/editor).
	useEffect(() => {
		if (!editor || !contentRef) return;
		contentRef.current = {
			editor,
			getHtml: () => serializeToTokens(editor.getHTML()),
			insertToken: (raw) => insertRawToken(editor, raw),
		};
		return () => {
			if (contentRef.current && contentRef.current.editor === editor) contentRef.current = null;
		};
	}, [editor, contentRef]);

	// --- Slash-Menü ---
	const [slashOpen, setSlashOpen] = useState(false);
	const [slashPos, setSlashPos] = useState({ x: 0, y: 0 });
	const [slashQuery] = useState("");
	const editorRef = useRef(null);
	const openSlash = useCallback(() => {
		const r = editorRef.current?.getBoundingClientRect();
		setSlashPos({ x: (r?.left || 100) + 60, y: (r?.top || 100) + 40 });
		setSlashOpen(true);
	}, []);
	const closeSlash = () => setSlashOpen(false);
	const onPick = (selection) => {
		if (selection.kind === "placeholder") onInsertItem({ kind: "chip", token: selection.item.token });
		else if (selection.kind === "snippet") onInsertItem({ kind: "snippet", snippet: selection.item });
		else if (selection.kind === "baustein") onInsertItem({ kind: "baustein", name: selection.item.name });
		closeSlash();
	};

	// --- Bild-Upload ---
	const handleImage = useCallback(() => {
		if (!editor) return;
		if (onImageUpload) fileInputRef.current?.click();
		else {
			const url = prompt("Bild-URL:");
			if (url) editor.chain().focus().setImage({ src: url }).run();
		}
	}, [editor, onImageUpload]);

	const onFileChosen = async (e) => {
		const file = e.target.files?.[0];
		e.target.value = "";
		if (!file || !editor) return;
		try {
			const url = await onImageUpload(file);
			if (url) editor.chain().focus().setImage({ src: url }).run();
		} catch (err) {
			alert("Bild-Upload fehlgeschlagen: " + ((err && err.message) || err));
		}
	};

	// Drag&Drop aus der Sidebar
	const [dragOver, setDragOver] = useState(false);
	const onDrop = (e) => {
		e.preventDefault();
		setDragOver(false);
		try {
			const data = JSON.parse(e.dataTransfer.getData("application/json"));
			if (data.kind === "placeholder") onInsertItem({ kind: "chip", token: data.token });
			else if (data.kind === "baustein") onInsertItem({ kind: "baustein", name: data.name });
		} catch (err) {
			/* ignore */
		}
	};

	return (
		<main className="center">
			<EditorToolbar
				editor={editor}
				disabled={!editable}
				onInsert={openSlash}
				onImage={handleImage}
				showGrid={showGrid}
				onToggleGrid={() => setShowGrid((v) => !v)}
			/>

			{safety && (
				<div className="editor-unsafe-banner">
					<Icon name="branch" size={14} />
					<span>
						Diese Vorlage enthält eine Struktur, die der Editor nicht verlustfrei abbilden kann
						{Object.keys(safety.lost || {}).length
							? ` (z. B. ${Object.keys(safety.lost).slice(0, 3).join(", ")})`
							: ""}
						. Read-only — bitte im klassischen Formular bearbeiten.
					</span>
				</div>
			)}

			<div className="editor-scroll" ref={editorRef}>
				<div
					className={`editor-canvas ${dragOver ? "drag-over" : ""} ${showGrid ? "" : "hv-no-grid"}`}
					onDragOver={(e) => {
						e.preventDefault();
						setDragOver(true);
					}}
					onDragLeave={() => setDragOver(false)}
					onDrop={onDrop}
				>
					{/* EditorContent und das BubbleMenu bleiben dauerhaft gemountet. Beim
					    Vorlagen-Laden (loading-Toggle) dürfen sie NICHT gegen einen Platzhalter
					    getauscht werden: TipTap/ProseMirror und tippy.js verwalten eigenes DOM
					    (das BubbleMenu hängt seinen Popper an document.body). Ein Unmount/Remount
					    während des React-Commits führt zu „removeChild: node is not a child"
					    und reißt die gesamte App ab. Der Ladezustand liegt daher nur als
					    Overlay über der Canvas, das BubbleMenu blendet sich via shouldShow aus. */}
					<EditorContent editor={editor} />
					{editor && <TableBubbleMenu editor={editor} />}
					{loading && <div className="editor-loading editor-loading-overlay">Vorlage wird geladen …</div>}
					{!loading && (
						<div className="editor-foot-hint">
							{editable
								? "Platzhalter & Bausteine sind ein Stück (als Ganzes löschbar). In Tabellen erscheint oben ein Menü (Spalte/Zeile +/−, Kopfzeile, löschen); ↻ wiederholt eine Zeile als {% for %}. Tabellen-Linien sind nur Bearbeitungshilfe – im PDF unsichtbar. Speichern oben rechts."
								: "Read-only (keine Schreibberechtigung)."}
						</div>
					)}
				</div>
			</div>

			<input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onFileChosen} />

			<SlashMenu open={slashOpen} x={slashPos.x} y={slashPos.y} query={slashQuery} onClose={closeSlash} onPick={onPick} />
		</main>
	);
};
