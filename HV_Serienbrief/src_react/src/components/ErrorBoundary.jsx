import React from "react";

// Root-Error-Boundary: Fängt Render-/Commit-Fehler (z. B. einen TipTap/React
// „removeChild"-Crash) ab, damit nicht die gesamte App stumm abgehängt wird und eine
// weiße Seite zurückbleibt. Zeigt stattdessen die echte Fehlermeldung + „Neu laden".
export class ErrorBoundary extends React.Component {
	constructor(props) {
		super(props);
		this.state = { error: null };
	}

	static getDerivedStateFromError(error) {
		return { error };
	}

	componentDidCatch(error, info) {
		// In die Konsole, damit der Stack beim Debuggen sichtbar bleibt.
		// eslint-disable-next-line no-console
		console.error("[Serienbrief-Editor] Render-Fehler:", error, info);
	}

	render() {
		if (!this.state.error) return this.props.children;
		const msg = (this.state.error && this.state.error.message) || String(this.state.error);
		return (
			<div
				style={{
					maxWidth: 640,
					margin: "80px auto",
					padding: 24,
					fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
					color: "#1a1a1a",
				}}
			>
				<h2 style={{ margin: "0 0 8px", fontSize: 18 }}>Der Editor ist abgestürzt</h2>
				<p style={{ margin: "0 0 16px", color: "#555", fontSize: 14 }}>
					Ein Render-Fehler hat die Oberfläche unterbrochen. Bitte neu laden — bleibt der
					Fehler bestehen, hilft die Meldung unten beim Eingrenzen.
				</p>
				<pre
					style={{
						background: "#f6f5f1",
						border: "1px solid #e0ddd5",
						borderRadius: 6,
						padding: "10px 12px",
						fontSize: 12,
						whiteSpace: "pre-wrap",
						wordBreak: "break-word",
						color: "#8a1f1f",
					}}
				>
					{msg}
				</pre>
				<button
					onClick={() => window.location.reload()}
					style={{
						marginTop: 16,
						padding: "8px 14px",
						border: "1px solid #c9c4b8",
						borderRadius: 6,
						background: "#fff",
						cursor: "pointer",
						fontSize: 14,
					}}
				>
					Neu laden
				</button>
			</div>
		);
	}
}
