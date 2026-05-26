import React from "react";

export class ErrorBoundary extends React.Component {
	constructor(props) {
		super(props);
		this.state = { error: null };
	}
	static getDerivedStateFromError(error) {
		return { error };
	}
	componentDidCatch(error, info) {
		// In der Konsole sichtbar; im Frappe-iframe via DevTools auffindbar.
		console.error("[bankimport] render error", error, info);
	}
	render() {
		if (this.state.error) {
			return (
				<div style={{ padding: 24, fontFamily: "sans-serif", color: "#b91c1c" }}>
					<h2>Fehler beim Rendern</h2>
					<pre style={{ whiteSpace: "pre-wrap" }}>{String(this.state.error?.stack || this.state.error)}</pre>
				</div>
			);
		}
		return this.props.children;
	}
}
