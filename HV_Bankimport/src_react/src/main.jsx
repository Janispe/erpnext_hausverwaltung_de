import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";

// Prototyp-Styles (globale body/100vh-Selektoren — daher iframe-isoliert) …
import "./styles/styles-base.css";
import "./styles/styles-stats.css";
import "./styles/styles-table.css";
import "./styles/styles-panel.css";
// … plus Ergänzungen für die neu hinzugekommenen, verdrahteten Komponenten.
import "./styles/app-extra.css";

ReactDOM.createRoot(document.getElementById("root")).render(
	<React.StrictMode>
		<ErrorBoundary>
			<App />
		</ErrorBoundary>
	</React.StrictMode>
);
