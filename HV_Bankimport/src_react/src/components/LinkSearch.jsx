import React, { useState, useEffect, useRef, useCallback } from "react";
import { Icon, Spinner } from "../helpers.jsx";

// Schlanke Autocomplete-Eingabe. `fetcher(txt)` liefert ein Promise auf
// [{ value, label?, description? }]. `onPick(item)` wird bei Auswahl gerufen.
export function LinkSearch({ placeholder, fetcher, onPick, autoFocus, disabled }) {
	const [txt, setTxt] = useState("");
	const [items, setItems] = useState([]);
	const [open, setOpen] = useState(false);
	const [loading, setLoading] = useState(false);
	const [active, setActive] = useState(0);
	const boxRef = useRef(null);
	const seq = useRef(0);

	const search = useCallback(
		async (q) => {
			const mine = ++seq.current;
			setLoading(true);
			try {
				const res = await fetcher(q);
				if (mine !== seq.current) return;
				setItems(res.items || []);
				setOpen(true);
				setActive(0);
			} catch (e) {
				if (mine === seq.current) setItems([]);
			} finally {
				if (mine === seq.current) setLoading(false);
			}
		},
		[fetcher]
	);

	useEffect(() => {
		const t = setTimeout(() => {
			if (txt.trim().length >= 1) search(txt.trim());
			else setItems([]);
		}, 200);
		return () => clearTimeout(t);
	}, [txt, search]);

	useEffect(() => {
		const onDoc = (e) => {
			if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
		};
		document.addEventListener("mousedown", onDoc);
		return () => document.removeEventListener("mousedown", onDoc);
	}, []);

	const pick = (item) => {
		onPick(item);
		setTxt("");
		setItems([]);
		setOpen(false);
	};

	const onKey = (e) => {
		if (!open || !items.length) return;
		if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
		else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
		else if (e.key === "Enter") { e.preventDefault(); pick(items[active]); }
		else if (e.key === "Escape") setOpen(false);
	};

	return (
		<div className="link-search" ref={boxRef}>
			<div className="link-search-input">
				{loading ? <Spinner size={13} /> : <Icon name="search" size={13} />}
				<input
					value={txt}
					placeholder={placeholder}
					autoFocus={autoFocus}
					disabled={disabled}
					onChange={(e) => setTxt(e.target.value)}
					onFocus={() => items.length && setOpen(true)}
					onKeyDown={onKey}
				/>
			</div>
			{open && items.length > 0 && (
				<div className="link-search-list">
					{items.map((it, i) => (
						<button
							key={it.value + i}
							type="button"
							className={`link-search-item ${i === active ? "active" : ""}`}
							onMouseEnter={() => setActive(i)}
							onClick={() => pick(it)}
						>
							<span className="ls-value">{it.label || it.value}</span>
							{it.description && <span className="ls-desc">{it.description}</span>}
						</button>
					))}
				</div>
			)}
		</div>
	);
}
