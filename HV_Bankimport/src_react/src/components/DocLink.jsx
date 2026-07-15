import React from "react";
import * as api from "../api.js";

export function DocLink({ doctype, docname, className, children, title, style, onOpen }) {
	if (!doctype || !docname) return null;
	const handleClick = (event) => {
		event.stopPropagation();
		if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
		event.preventDefault();
		(onOpen || (() => api.openDoc(doctype, docname)))();
	};
	return (
		<a
			href={api.docHref(doctype, docname)}
			target="_top"
			className={className}
			title={title || `${doctype} ${docname} öffnen`}
			style={style}
			onClick={handleClick}
		>
			{children || docname}
		</a>
	);
}
