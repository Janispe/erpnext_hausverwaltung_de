frappe.pages["hausverwaltung-assistant"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Assistent"),
		single_column: true,
	});

	page.set_primary_action(__("Suchen"), () => {
		const input = document.querySelector(".hv-assistant-input");
		if (input) {
			window.hvAssistantSend(input.value);
		}
	});

	renderHausverwaltungAssistant(page.body);
};

function renderHausverwaltungAssistant(pageBody) {
	const root = $(pageBody);
	root.html(`
		<div class="hv-assistant">
			<button class="hv-assistant-backdrop" type="button" aria-label="${__("Seitenbereich schliessen")}" tabindex="-1"></button>
			<div class="hv-assistant-shell">
				<aside class="hv-assistant-conversations" id="hv-assistant-conversations" aria-label="${__("Chats")}">
					<div class="hv-assistant-conversations-head">
						<div class="hv-assistant-results-title">${__("Chats")}</div>
						<div class="hv-assistant-panel-actions">
							<button class="btn btn-xs btn-default hv-assistant-new" type="button">${__("Neu")}</button>
							<button class="btn btn-xs btn-default hv-assistant-panel-close" type="button" aria-label="${__("Chats schliessen")}">×</button>
						</div>
					</div>
					<div class="hv-assistant-conversation-list"></div>
				</aside>
				<div class="hv-assistant-main">
					<div class="hv-assistant-mobile-bar">
						<button class="hv-assistant-mobile-nav hv-assistant-open-chats" type="button" aria-controls="hv-assistant-conversations" aria-expanded="false">
							<span aria-hidden="true">☰</span> ${__("Chats")}
						</button>
						<div class="hv-assistant-mobile-title">${__("Neuer Chat")}</div>
						<button class="hv-assistant-mobile-nav hv-assistant-open-results" type="button" aria-controls="hv-assistant-results" aria-expanded="false">
							${__("Treffer")} <span class="hv-assistant-results-count">0</span>
						</button>
					</div>
					<div class="hv-assistant-messages" aria-live="polite"></div>
					<form class="hv-assistant-form">
						<input class="hv-assistant-input" type="search" autocomplete="off" placeholder="${__("Frage stellen oder Stammdaten suchen")}">
						<select class="hv-assistant-engine" aria-label="${__("Engine")}" title="${__("Ausfuehrungsart fuer diesen Chat")}">
							<option value="classic">${__("Bestehend")}</option>
							<option value="mistral_agents">${__("Mistral Agents (Prototyp)")}</option>
							<option value="mistral_basic">${__("Mistral Basic + Rechner")}</option>
						</select>
						<select class="hv-assistant-model" aria-label="${__("Modell")}" title="${__("Modell fuer diese Anfrage")}">
							<option value="default">${__("Standardmodell")}</option>
						</select>
						<button class="btn btn-primary hv-assistant-submit" type="submit">${__("Senden")}</button>
					</form>
				</div>
				<aside class="hv-assistant-results" id="hv-assistant-results" aria-label="${__("Treffer")}">
					<div class="hv-assistant-results-head">
						<div class="hv-assistant-results-title">${__("Treffer")}</div>
						<button class="btn btn-xs btn-default hv-assistant-panel-close" type="button" aria-label="${__("Treffer schliessen")}">×</button>
					</div>
					<div class="hv-assistant-results-list"></div>
				</aside>
			</div>
		</div>
		<style>
			.hv-assistant {
				margin: -15px -15px 0;
				min-height: calc(100vh - 110px);
				background: #f7f7f5;
				color: #1f2328;
				position: relative;
			}
			.hv-assistant-backdrop,
			.hv-assistant-mobile-bar,
			.hv-assistant-panel-close {
				display: none;
			}
			.hv-assistant-shell {
				display: grid;
				grid-template-columns: 260px minmax(0, 1fr) 360px;
				gap: 16px;
				max-width: 1320px;
				margin: 0 auto;
				padding: 18px;
			}
			.hv-assistant-conversations,
			.hv-assistant-main,
			.hv-assistant-results {
				background: #fff;
				border: 1px solid #deded8;
				border-radius: 8px;
			}
			.hv-assistant-main {
				display: grid;
				grid-template-rows: minmax(360px, 1fr) auto;
				min-height: calc(100vh - 150px);
				overflow: hidden;
			}
			.hv-assistant-messages {
				padding: 18px;
				overflow: auto;
				min-height: 0;
				overscroll-behavior: contain;
			}
			.hv-assistant-message {
				max-width: 760px;
				margin-bottom: 12px;
				padding: 10px 12px;
				border-radius: 8px;
				line-height: 1.45;
				white-space: pre-wrap;
			}
			.hv-assistant-message.user {
				margin-left: auto;
				background: #20312b;
				color: #fff;
			}
			.hv-assistant-message.assistant {
				background: #f2f3ef;
				color: #1f2328;
			}
			.hv-assistant-message.error {
				background: #fff1f0;
				color: #8a1f11;
				border: 1px solid #f0b8ad;
			}
			.hv-assistant-usage {
				margin-top: 8px;
				padding-top: 7px;
				border-top: 1px solid rgba(0, 0, 0, 0.08);
				color: #68726d;
				font-size: 11px;
				white-space: normal;
			}
			.hv-assistant-toolcalls {
				margin-top: 8px;
				border-top: 1px solid rgba(0, 0, 0, 0.08);
				padding-top: 7px;
				font-size: 12px;
			}
			.hv-assistant-toolcalls summary {
				cursor: pointer;
				color: #59636e;
				font-weight: 600;
			}
			.hv-assistant-analysis {
				margin-top: 9px;
				border: 1px solid #d7ddd8;
				border-radius: 7px;
				background: rgba(255, 255, 255, 0.72);
				font-size: 12px;
				white-space: normal;
			}
			.hv-assistant-analysis > summary {
				cursor: pointer;
				padding: 7px 9px;
				color: #35463f;
				font-weight: 600;
			}
			.hv-assistant-analysis.has-warning > summary {
				color: #875a10;
			}
			.hv-assistant-analysis-step {
				margin: 0 8px 8px;
				padding: 8px;
				border: 1px solid #e1e4df;
				border-radius: 6px;
				background: #fff;
			}
			.hv-assistant-analysis-step.error {
				border-color: #efc2ba;
				background: #fff8f6;
			}
			.hv-assistant-analysis-title {
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 8px;
				margin-bottom: 5px;
				font-weight: 600;
			}
			.hv-assistant-analysis-status {
				font-size: 10px;
				font-weight: 600;
				text-transform: uppercase;
				letter-spacing: 0.03em;
				color: #397353;
			}
			.hv-assistant-analysis-step.error .hv-assistant-analysis-status {
				color: #a52a1a;
			}
			.hv-assistant-analysis-row {
				display: grid;
				grid-template-columns: minmax(82px, 110px) minmax(0, 1fr);
				gap: 7px;
				padding-top: 3px;
			}
			.hv-assistant-analysis-label {
				color: #69736e;
			}
			.hv-assistant-analysis-value {
				min-width: 0;
				white-space: pre-wrap;
				word-break: break-word;
				font-family: var(--font-stack);
			}
			.hv-assistant-analysis-warning {
				margin-top: 6px;
				padding: 6px 7px;
				border-radius: 5px;
				background: #fff4d6;
				color: #754f0d;
			}
			.hv-assistant-analysis-exchange {
				margin-top: 7px;
				border-top: 1px solid #e7e9e5;
				padding-top: 6px;
			}
			.hv-assistant-analysis-exchange > summary {
				cursor: pointer;
				color: #506159;
				font-weight: 600;
			}
			.hv-assistant-analysis-exchange-label {
				margin-top: 7px;
				color: #69736e;
				font-weight: 600;
			}
			.hv-assistant-analysis-exchange pre {
				max-height: 420px;
				margin: 4px 0 0;
				overflow: auto;
				white-space: pre-wrap;
				word-break: break-word;
				font-size: 11px;
				line-height: 1.35;
				color: #3d444d;
				background: #f7f8f6;
				border: 1px solid #e7e9e5;
				border-radius: 5px;
				padding: 7px;
			}
			.hv-assistant-analysis-usage-note {
				margin-top: 7px;
				color: #69736e;
				font-size: 11px;
			}
			.hv-assistant-reasoning {
				margin-top: 9px;
				border: 1px solid #d8d6e6;
				border-radius: 7px;
				background: #faf9ff;
				font-size: 12px;
				white-space: normal;
			}
			.hv-assistant-reasoning > summary {
				cursor: pointer;
				padding: 7px 9px;
				color: #51476c;
				font-weight: 600;
			}
			.hv-assistant-reasoning-note {
				margin: 0 9px 7px;
				color: #716982;
				line-height: 1.4;
			}
			.hv-assistant-reasoning-content {
				margin: 0 8px 8px;
				padding: 8px;
				border: 1px solid #e4e1ef;
				border-radius: 6px;
				background: #fff;
				color: #3f394d;
				font-family: var(--font-stack);
				font-size: 12px;
				line-height: 1.45;
				white-space: pre-wrap;
				word-break: break-word;
			}
			.hv-assistant-toolcall {
				margin-top: 7px;
				padding: 7px;
				border: 1px solid #deded8;
				border-radius: 6px;
				background: #fff;
			}
			.hv-assistant-toolcall-title {
				font-weight: 600;
				margin-bottom: 4px;
			}
			.hv-assistant-toolcall pre {
				margin: 0;
				white-space: pre-wrap;
				word-break: break-word;
				font-size: 11px;
				line-height: 1.35;
				color: #3d444d;
				background: transparent;
				border: 0;
				padding: 0;
			}
			.hv-assistant-form {
				display: grid;
				grid-template-columns: minmax(0, 1fr) minmax(150px, 190px) minmax(170px, 220px) auto;
				gap: 8px;
				padding: 12px;
				border-top: 1px solid #deded8;
			}
			.hv-assistant-input {
				height: 36px;
				border: 1px solid #cfcfc8;
				border-radius: 6px;
				padding: 0 12px;
				font-size: 14px;
				background: #fff;
				min-width: 0;
			}
			.hv-assistant-engine,
			.hv-assistant-model {
				height: 36px;
				border: 1px solid #cfcfc8;
				border-radius: 6px;
				padding: 0 30px 0 10px;
				font-size: 13px;
				background: #fff;
			}
			.hv-assistant-submit {
				height: 36px;
			}
			.hv-assistant-input:focus-visible,
			.hv-assistant-engine:focus-visible,
			.hv-assistant-model:focus-visible,
			.hv-assistant-mobile-nav:focus-visible,
			.hv-assistant-panel-close:focus-visible {
				outline: 2px solid #4c8bf5;
				outline-offset: 2px;
			}
			.hv-assistant-results {
				min-height: calc(100vh - 150px);
				padding: 14px;
			}
			.hv-assistant-conversations {
				min-height: calc(100vh - 150px);
				padding: 14px;
			}
			.hv-assistant-conversations-head {
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 8px;
				margin-bottom: 10px;
			}
			.hv-assistant-panel-actions,
			.hv-assistant-results-head {
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 8px;
			}
			.hv-assistant-results-head .hv-assistant-results-title {
				margin-bottom: 0;
			}
			.hv-assistant-results-title {
				font-weight: 600;
				font-size: 13px;
				text-transform: uppercase;
				color: #666;
				margin-bottom: 10px;
			}
			.hv-assistant-conversations-head .hv-assistant-results-title {
				margin-bottom: 0;
			}
			.hv-assistant-conversation {
				width: 100%;
				display: block;
				text-align: left;
				border: 1px solid transparent;
				border-radius: 8px;
				padding: 9px 10px;
				margin-bottom: 6px;
				background: transparent;
				color: #1f2328;
			}
			.hv-assistant-conversation:hover,
			.hv-assistant-conversation.active {
				background: #f2f3ef;
				border-color: #deded8;
			}
			.hv-assistant-conversation-title {
				font-size: 13px;
				font-weight: 600;
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
			}
			.hv-assistant-conversation-meta {
				color: #777;
				font-size: 11px;
				margin-top: 3px;
			}
			.hv-assistant-result {
				border: 1px solid #deded8;
				border-radius: 8px;
				padding: 12px;
				margin-bottom: 10px;
				background: #fff;
			}
			.hv-assistant-result-title {
				font-weight: 600;
				margin-bottom: 3px;
			}
			.hv-assistant-result-subtitle,
			.hv-assistant-result-meta {
				color: #686868;
				font-size: 12px;
				line-height: 1.4;
			}
			.hv-assistant-route-row {
				display: flex;
				flex-wrap: wrap;
				gap: 6px;
				margin-top: 10px;
			}
			.hv-assistant-empty {
				color: #777;
				font-size: 13px;
				padding: 8px 0;
			}
			@media (max-width: 980px) {
				.hv-assistant {
					margin: -15px -15px 0;
					min-height: calc(100dvh - 98px);
					overflow: hidden;
				}
				.hv-assistant-shell {
					display: block;
					max-width: none;
					padding: 10px;
				}
				.hv-assistant-main {
					grid-template-rows: auto minmax(0, 1fr) auto;
					height: calc(100dvh - 118px);
					min-height: 0;
					border-radius: 10px;
				}
				.hv-assistant-mobile-bar {
					display: grid;
					grid-template-columns: auto minmax(0, 1fr) auto;
					align-items: center;
					gap: 8px;
					min-height: 48px;
					padding: 6px 8px;
					border-bottom: 1px solid #deded8;
					background: #fff;
				}
				.hv-assistant-mobile-nav {
					min-height: 36px;
					border: 1px solid #d6d8d3;
					border-radius: 8px;
					padding: 0 10px;
					background: #f7f8f5;
					color: #35423d;
					font-size: 12px;
					font-weight: 600;
				}
				.hv-assistant-results-count {
					display: inline-flex;
					align-items: center;
					justify-content: center;
					min-width: 19px;
					height: 19px;
					margin-left: 3px;
					padding: 0 5px;
					border-radius: 10px;
					background: #20312b;
					color: #fff;
					font-size: 10px;
				}
				.hv-assistant-mobile-title {
					overflow: hidden;
					text-align: center;
					text-overflow: ellipsis;
					white-space: nowrap;
					font-size: 13px;
					font-weight: 600;
				}
				.hv-assistant-conversations,
				.hv-assistant-results {
					position: fixed;
					top: 0;
					bottom: 0;
					z-index: 1061;
					width: min(88vw, 380px);
					min-height: 0;
					padding: max(16px, env(safe-area-inset-top)) 14px max(16px, env(safe-area-inset-bottom));
					overflow: auto;
					border-radius: 0;
					box-shadow: 0 16px 50px rgba(20, 28, 24, 0.24);
					transition: transform 180ms ease;
				}
				.hv-assistant-conversations {
					left: 0;
					transform: translateX(-105%);
				}
				.hv-assistant-results {
					right: 0;
					transform: translateX(105%);
				}
				.hv-assistant.mobile-chats-open .hv-assistant-conversations,
				.hv-assistant.mobile-results-open .hv-assistant-results {
					transform: translateX(0);
				}
				.hv-assistant-panel-close {
					display: inline-flex;
					align-items: center;
					justify-content: center;
					width: 36px;
					height: 36px;
					padding: 0;
					font-size: 22px;
					line-height: 1;
				}
				.hv-assistant.mobile-chats-open .hv-assistant-backdrop,
				.hv-assistant.mobile-results-open .hv-assistant-backdrop {
					display: block;
					position: fixed;
					inset: 0;
					z-index: 1060;
					width: 100%;
					height: 100%;
					border: 0;
					background: rgba(18, 24, 21, 0.38);
				}
				.hv-assistant-conversation,
				.hv-assistant-result {
					min-height: 48px;
				}
				.hv-assistant-route-row .btn {
					min-height: 40px;
				}
			}
			@media (max-width: 560px) {
				.hv-assistant-shell {
					padding: 0;
				}
				.hv-assistant-main {
					height: calc(100dvh - 99px);
					min-height: 0;
					border-left: 0;
					border-right: 0;
					border-radius: 0;
				}
				.hv-assistant-messages {
					padding: 12px 10px 6px;
				}
				.hv-assistant-message {
					max-width: 92%;
					margin-bottom: 10px;
					padding: 9px 10px;
					font-size: 14px;
					word-break: break-word;
				}
				.hv-assistant-message.assistant,
				.hv-assistant-message.error {
					max-width: 100%;
				}
				.hv-assistant-form {
					grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
					gap: 7px;
					padding: 9px 9px max(9px, env(safe-area-inset-bottom));
					background: #fff;
				}
				.hv-assistant-input {
					grid-column: 1 / -1;
					height: 44px;
					font-size: 16px;
				}
				.hv-assistant-engine,
				.hv-assistant-model {
					width: 100%;
					min-width: 0;
					height: 42px;
					padding-left: 8px;
					font-size: 12px;
				}
				.hv-assistant-submit {
					height: 42px;
					padding-left: 13px;
					padding-right: 13px;
				}
				.hv-assistant-analysis-row {
					grid-template-columns: 1fr;
					gap: 1px;
				}
				.hv-assistant-analysis-title {
					align-items: flex-start;
				}
				.hv-assistant-analysis-exchange pre,
				.hv-assistant-reasoning-content,
				.hv-assistant-toolcall pre {
					max-height: 55dvh;
					font-size: 10px;
				}
			}
		</style>
	`);

	const messagesEl = root.find(".hv-assistant-messages");
	const resultsEl = root.find(".hv-assistant-results-list");
	const conversationsEl = root.find(".hv-assistant-conversation-list");
	const assistantRoot = root.find(".hv-assistant");
	const conversationsPanel = root.find(".hv-assistant-conversations");
	const resultsPanel = root.find(".hv-assistant-results");
	const chatsToggle = root.find(".hv-assistant-open-chats");
	const resultsToggle = root.find(".hv-assistant-open-results");
	const mobileTitle = root.find(".hv-assistant-mobile-title");
	const resultsCount = root.find(".hv-assistant-results-count");
	const form = root.find(".hv-assistant-form");
	const input = root.find(".hv-assistant-input");
	const engineSelect = root.find(".hv-assistant-engine");
	const modelSelect = root.find(".hv-assistant-model");
	let conversationId = null;
	let activeRunId = null;
	let pollGeneration = 0;
	const ASSISTANT_POLL_INTERVAL_MS = 1000;
	const ASSISTANT_POLL_DEADLINE_MS = 20 * 60 * 1000;
	const mobileLayout = window.matchMedia("(max-width: 980px)");
	const compactLayout = window.matchMedia("(max-width: 560px)");

	const syncMobilePanels = () => {
		const chatsOpen = assistantRoot.hasClass("mobile-chats-open");
		const resultsOpen = assistantRoot.hasClass("mobile-results-open");
		chatsToggle.attr("aria-expanded", chatsOpen ? "true" : "false");
		resultsToggle.attr("aria-expanded", resultsOpen ? "true" : "false");
		if (mobileLayout.matches) {
			conversationsPanel.attr("aria-hidden", chatsOpen ? "false" : "true");
			resultsPanel.attr("aria-hidden", resultsOpen ? "false" : "true");
			conversationsPanel.prop("inert", !chatsOpen);
			resultsPanel.prop("inert", !resultsOpen);
		} else {
			conversationsPanel.removeAttr("aria-hidden").prop("inert", false);
			resultsPanel.removeAttr("aria-hidden").prop("inert", false);
		}
	};

	const closeMobilePanels = () => {
		assistantRoot.removeClass("mobile-chats-open mobile-results-open");
		syncMobilePanels();
	};

	const openMobilePanel = (panel) => {
		assistantRoot.toggleClass("mobile-chats-open", panel === "chats");
		assistantRoot.toggleClass("mobile-results-open", panel === "results");
		syncMobilePanels();
		const target = panel === "chats" ? conversationsPanel : resultsPanel;
		window.setTimeout(() => target.find("button:visible").first().trigger("focus"), 190);
	};

	const focusComposer = () => {
		if (!compactLayout.matches) input.trigger("focus");
	};

	chatsToggle.on("click", () => openMobilePanel("chats"));
	resultsToggle.on("click", () => openMobilePanel("results"));
	root.find(".hv-assistant-backdrop, .hv-assistant-panel-close").on("click", closeMobilePanels);
	$(document)
		.off("keydown.hvAssistantMobile")
		.on("keydown.hvAssistantMobile", (event) => {
			if (event.key === "Escape") closeMobilePanels();
		});
	if (mobileLayout.addEventListener) {
		mobileLayout.addEventListener("change", closeMobilePanels);
	} else {
		mobileLayout.addListener(closeMobilePanels);
	}
	syncMobilePanels();

	const loadAssistantModels = async () => {
		try {
			const response = await frappe.call({
				method: "hausverwaltung.hausverwaltung.services.assistant.get_assistant_models",
			});
			const data = response.message || {};
			modelSelect.empty();
			(data.models || []).forEach((model) => {
				const option = document.createElement("option");
				option.value = model.value;
				option.textContent = model.label || model.value;
				option.title = model.description || "";
				modelSelect.append(option);
			});
			modelSelect.val(data.default || "default");
		} catch (error) {
			// Das zentral konfigurierte Standardmodell bleibt als sicherer Fallback nutzbar.
			modelSelect.val("default");
		}
	};

	const appendToolCalls = (node, toolCalls) => {
		if (!toolCalls || !toolCalls.length) return;
		const details = document.createElement("details");
		details.className = "hv-assistant-toolcalls";
		const summary = document.createElement("summary");
		summary.textContent = `${__("Tool Calls")} (${toolCalls.length})`;
		details.append(summary);
		toolCalls.forEach((toolCall) => {
			const item = document.createElement("div");
			item.className = "hv-assistant-toolcall";
			const title = document.createElement("div");
			title.className = "hv-assistant-toolcall-title";
			const count = Number.isFinite(Number(toolCall.result_count)) ? ` - ${toolCall.result_count} ${__("Treffer")}` : "";
			title.textContent = `${toolCall.name || __("Tool")}${count}`;
			const pre = document.createElement("pre");
			pre.textContent = JSON.stringify(
				{
					arguments: toolCall.arguments || {},
					output: toolCall.output || null,
					error: toolCall.error || null,
				},
				null,
				2
			);
			item.append(title);
			item.append(pre);
			details.append(item);
		});
		node.append(details);
	};

	const analysisFromToolCall = (toolCall) => {
		if (toolCall.analysis && typeof toolCall.analysis === "object") {
			return toolCall.analysis;
		}
		const args = toolCall.arguments || {};
		return {
			status: toolCall.error ? "error" : "success",
			tool: toolCall.name || "",
			source: args.view || args.source || args.doctype || toolCall.name || "",
			filters: args.filters || null,
			aggregation: args.aggregate || null,
			order_by: args.order_by || null,
			result_count: toolCall.result_count,
			warnings: toolCall.error
				? [__("Werkzeug fehlgeschlagen; das Ergebnis ist nicht belastbar.")]
				: [],
		};
	};

	const compactJson = (value) => {
		if (value === null || value === undefined || value === "") return "";
		if (typeof value === "string") return value;
		return JSON.stringify(value, null, 2);
	};

	const aggregationLabel = (aggregation) => {
		if (!aggregation || typeof aggregation !== "object") return "";
		const operation = aggregation.op || aggregation.operation || "";
		const field = aggregation.field ? `(${aggregation.field})` : "";
		const group = aggregation.group_by ? ` ${__("nach")} ${aggregation.group_by}` : "";
		return `${operation}${field}${group}`.trim();
	};

	const aggregationResultLabel = (aggregate) => {
		if (!aggregate || typeof aggregate !== "object") return "";
		if (Array.isArray(aggregate.groups)) {
			const count = aggregate.group_count ?? aggregate.groups.length;
			return `${count} ${__("Gruppen")}\n${compactJson(aggregate.groups)}`;
		}
		if (aggregate.value === undefined || aggregate.value === null) return compactJson(aggregate);
		const count = aggregate.count !== undefined ? ` (${aggregate.count} ${__("Werte")})` : "";
		return `${aggregate.value}${count}`;
	};

	const appendAnalysisRow = (node, label, value) => {
		const text = compactJson(value);
		if (!text) return;
		const row = document.createElement("div");
		row.className = "hv-assistant-analysis-row";
		const labelNode = document.createElement("div");
		labelNode.className = "hv-assistant-analysis-label";
		labelNode.textContent = label;
		const valueNode = document.createElement("div");
		valueNode.className = "hv-assistant-analysis-value";
		valueNode.textContent = text;
		row.append(labelNode, valueNode);
		node.append(row);
	};

	const modelRoundUsageLabel = (usage) => {
		if (!usage || typeof usage !== "object") return "";
		return [
			`${__("Gesamt")}: ${formatTokenCount(usage.total_tokens)}`,
			`${__("Eingabe")}: ${formatTokenCount(usage.prompt_tokens)}`,
			`${__("Ausgabe")}: ${formatTokenCount(usage.completion_tokens)}`,
		].join(" · ");
	};

	const appendToolExchange = (node, toolCall) => {
		if (!toolCall || typeof toolCall !== "object") return;
		const details = document.createElement("details");
		details.className = "hv-assistant-analysis-exchange";
		const summary = document.createElement("summary");
		summary.textContent = `${__("Vollstaendiger Tool-Aufruf")} / ${__("Antwort an Mistral")}`;
		details.append(summary);

		const appendJson = (label, value) => {
			const title = document.createElement("div");
			title.className = "hv-assistant-analysis-exchange-label";
			title.textContent = label;
			const pre = document.createElement("pre");
			pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
			details.append(title, pre);
		};

		const requestedArguments = toolCall.requested_arguments || toolCall.arguments || {};
		appendJson(__("Vom Modell angefordert"), requestedArguments);
		if (JSON.stringify(requestedArguments) !== JSON.stringify(toolCall.arguments || {})) {
			appendJson(__("Tatsaechlich ausgefuehrt"), toolCall.arguments || {});
		}
		if (Object.prototype.hasOwnProperty.call(toolCall, "output")) {
			appendJson(__("Antwort an Mistral"), toolCall.output);
		} else {
			const note = document.createElement("div");
			note.className = "hv-assistant-analysis-usage-note";
			note.textContent = __("Fuer diesen aelteren Aufruf wurde die Modellantwort noch nicht gespeichert.");
			details.append(note);
		}
		if (toolCall.error) appendJson(__("Fehler"), toolCall.error);

		const requestUsage = modelRoundUsageLabel(toolCall.model_request_usage);
		if (requestUsage) {
			const shared = Number(toolCall.model_request_usage_shared_calls || 0);
			const round = Number(toolCall.model_request_usage?.round || 0);
			const roundLabel = round ? `${__("Mistral-Runde")} ${round}: ${__("Toolwahl")}` : __("Toolwahl-Runde");
			const label = shared > 1
				? `${roundLabel} (${shared} ${__("Tools gemeinsam")})`
				: roundLabel;
			appendAnalysisRow(details, label, requestUsage);
		}
		const followupUsage = modelRoundUsageLabel(toolCall.model_followup_usage);
		if (followupUsage) {
			const shared = Number(toolCall.model_followup_usage_shared_calls || 0);
			const round = Number(toolCall.model_followup_usage?.round || 0);
			const roundLabel = round
				? `${__("Mistral-Runde")} ${round}: ${__("nach Toolantwort")}`
				: __("Folgerunde nach Toolantwort");
			const label = shared > 1
				? `${roundLabel} (${shared} ${__("Tools gemeinsam")})`
				: roundLabel;
			appendAnalysisRow(details, label, followupUsage);
		}
		if (requestUsage || followupUsage) {
			const note = document.createElement("div");
			note.className = "hv-assistant-analysis-usage-note";
			note.textContent = __(
				"Tokenwerte gelten fuer die gesamte Mistral-API-Runde inklusive Chatkontext, nicht nur fuer dieses Tool. Dieselbe Runde kann bei zwei benachbarten Schritten erscheinen und darf dann nicht doppelt addiert werden."
			);
			details.append(note);
		}
		node.append(details);
	};

	const appendAnalysis = (node, toolCalls) => {
		if (!toolCalls || !toolCalls.length) return;
		const steps = toolCalls.map(analysisFromToolCall);
		const hasWarning = steps.some(
			(step) => step.status === "error" || (step.warnings && step.warnings.length)
		);
		const details = document.createElement("details");
		details.className = `hv-assistant-analysis${hasWarning ? " has-warning" : ""}`;
		const summary = document.createElement("summary");
		summary.textContent = hasWarning
			? `${__("Analyse")} - ${__("Pruefung erforderlich")} (${steps.length})`
			: `${__("Analyse")} (${steps.length} ${__("Schritte")})`;
		details.append(summary);
		steps.forEach((step, index) => {
			const toolCall = toolCalls[index] || {};
			const item = document.createElement("div");
			item.className = `hv-assistant-analysis-step${step.status === "error" ? " error" : ""}`;
			const title = document.createElement("div");
			title.className = "hv-assistant-analysis-title";
			const titleText = document.createElement("span");
			titleText.textContent = `${index + 1}. ${step.source || step.tool || __("Abfrage")}`;
			const status = document.createElement("span");
			status.className = "hv-assistant-analysis-status";
			status.textContent = step.status === "error" ? __("Fehler") : __("Erfolgreich");
			title.append(titleText, status);
			item.append(title);
			appendAnalysisRow(
				item,
				__("Mistral-Runde"),
				toolCall.model_request_usage?.round || toolCall.model_request_round
			);
			appendAnalysisRow(item, __("Werkzeug"), step.tool);
			appendAnalysisRow(item, __("Filter"), step.filters);
			appendAnalysisRow(
				item,
				__("Berechnung"),
				aggregationLabel(step.aggregation) || step.operation
			);
			appendAnalysisRow(
				item,
				__("Ergebnis"),
				aggregationResultLabel(step.aggregation_result) || step.value
			);
			appendAnalysisRow(item, __("Gruppierung"), step.group_by);
			if (Array.isArray(step.groups)) {
				const suffix = step.groups_truncated ? `\n${__("Weitere Gruppen im vollstaendigen Tool-Ergebnis.")}` : "";
				appendAnalysisRow(
					item,
					`${__("Gruppenergebnisse")} (${step.group_count ?? step.groups.length})`,
					`${compactJson(step.groups)}${suffix}`
				);
			}
			appendAnalysisRow(item, __("Treffer"), step.result_count);
			appendAnalysisRow(item, __("Verwendet"), step.rows_used);
			appendAnalysisRow(item, __("Uebersprungen"), step.rows_skipped);
			appendAnalysisRow(item, __("Sortierung"), step.order_by);
			const error = toolCall.error;
			if (error) appendAnalysisRow(item, __("Fehler"), error.message || error);
			(step.warnings || []).forEach((warning) => {
				const warningNode = document.createElement("div");
				warningNode.className = "hv-assistant-analysis-warning";
				warningNode.textContent = warning;
				item.append(warningNode);
			});
			appendToolExchange(item, toolCall);
			details.append(item);
		});
		node.append(details);
	};

	const textFromAny = (value) => {
		if (value === null || value === undefined) return "";
		if (typeof value === "string") return value;
		if (typeof value === "number" || typeof value === "boolean") return String(value);
		if (Array.isArray(value)) {
			return value.map(textFromAny).filter(Boolean).join("\n");
		}
		if (typeof value === "object") {
			return (
				value.message ||
				value.exc ||
				value.exception ||
				value.error ||
				JSON.stringify(value, null, 2)
			);
		}
		return String(value);
	};

	const errorText = (err) => {
		try {
			if (err?._server_messages) {
				return JSON.parse(err._server_messages)
					.map((message) => textFromAny(JSON.parse(message).message || JSON.parse(message)))
					.filter(Boolean)
					.join("\n");
			}
		} catch (error) {
			return textFromAny(err?._server_messages);
		}
		if (Number(err?.status) === 0 || Number(err?.readyState) === 0) {
			return __(
				"Die Anfrage wurde im Browser abgebrochen oder es kam keine HTTP-Antwort zurueck. " +
				"Bitte pruefe Netzwerk/Reload/Session und versuche es erneut. Wenn es wieder passiert, " +
				"ist die Anfrage vermutlich zu lang oder der Proxy hat sie beendet."
			);
		}
		return textFromAny(err?.message || err?.responseJSON || err) || __("Unbekannter Fehler.");
	};

	const appendReasoning = (node, reasoning) => {
		const text = textFromAny(reasoning).trim();
		if (!text) return;
		const details = document.createElement("details");
		details.className = "hv-assistant-reasoning";
		const summary = document.createElement("summary");
		summary.textContent = __("Modell-Reasoning (nicht verifiziert)");
		const note = document.createElement("div");
		note.className = "hv-assistant-reasoning-note";
		note.textContent = __(
			"Von Mistral gelieferte interne Ueberlegungen; sie koennen unvollstaendig oder fehlerhaft sein."
		);
		const content = document.createElement("pre");
		content.className = "hv-assistant-reasoning-content";
		content.textContent = text;
		details.append(summary, note, content);
		node.append(details);
	};

	const formatTokenCount = (value) => {
		const number = Number(value || 0);
		return Number.isFinite(number) ? number.toLocaleString("de-DE") : "0";
	};

	const appendUsage = (node, usage) => {
		if (!usage || typeof usage !== "object" || !Number(usage.calls || usage.total_tokens)) return;
		const parts = [
			`${__("Tokenverbrauch")}: ${formatTokenCount(usage.total_tokens)}`,
			`${__("Eingabe")}: ${formatTokenCount(usage.prompt_tokens)}`,
			`${__("Ausgabe")}: ${formatTokenCount(usage.completion_tokens)}`,
			`${__("API-Aufrufe")}: ${formatTokenCount(usage.calls)}`,
		];
		if (Number(usage.cached_prompt_tokens || 0) > 0) {
			parts.push(`${__("davon gecacht")}: ${formatTokenCount(usage.cached_prompt_tokens)}`);
		}
		const meta = document.createElement("div");
		meta.className = "hv-assistant-usage";
		meta.textContent = parts.join(" · ");
		node.append(meta);
	};

	const addMessage = (kind, text, toolCalls, reasoning, usage) => {
		const node = document.createElement("div");
		node.className = `hv-assistant-message ${kind}`;
		node.textContent = textFromAny(text);
		appendUsage(node, usage);
		appendReasoning(node, reasoning);
		appendAnalysis(node, toolCalls);
		appendToolCalls(node, toolCalls);
		messagesEl.append(node);
		messagesEl.scrollTop(messagesEl[0].scrollHeight);
		return node;
	};

	const setComposerDisabled = (disabled) => {
		form.find("button, input, select").prop("disabled", Boolean(disabled));
	};

	const renderRunProgress = (node, progress = {}) => {
		const result = progress.result || {};
		const answer = textFromAny(result.answer || progress.answer || "").trim();
		const stage = textFromAny(progress.stage || "").trim();
		const status = progress.status || "running";
		const failure = status === "failed" ? textFromAny(progress.error || result.error || "").trim() : "";
		const text = failure || answer || stage || (status === "queued" ? __("Anfrage wartet ...") : __("Suche laeuft ..."));
		const reasoning = result.reasoning || progress.reasoning || "";
		const toolCalls = result.tool_calls || progress.tool_calls || [];
		const usage = result.mistral_usage || progress.mistral_usage || {};
		node.className = `hv-assistant-message ${status === "failed" ? "error" : "assistant"}`;
		node.textContent = text;
		appendUsage(node, usage);
		appendReasoning(node, reasoning);
		appendAnalysis(node, toolCalls);
		appendToolCalls(node, toolCalls);
		if (progress.matches || result.matches) {
			renderResults(result.matches || progress.matches || []);
		}
		messagesEl.scrollTop(messagesEl[0].scrollHeight);
	};

	const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

	const pollAssistantRun = async (runId, pending, generation, initialProgress = null) => {
		const deadline = Date.now() + ASSISTANT_POLL_DEADLINE_MS;
		let progress = initialProgress;
		while (generation === pollGeneration && Date.now() < deadline) {
			if (!progress) {
				try {
					const response = await frappe.call({
						method: "hausverwaltung.hausverwaltung.services.assistant_async.get_assistant_run_progress",
						args: { run_id: runId },
					});
					progress = response.message || {};
				} catch (error) {
					if (generation !== pollGeneration) return null;
					pending.textContent = __("Verbindung unterbrochen; der Assistent arbeitet im Hintergrund weiter ...");
					await wait(ASSISTANT_POLL_INTERVAL_MS * 2);
					continue;
				}
			}

			if (generation !== pollGeneration) return null;
			renderRunProgress(pending, progress);
			if (progress.status === "completed") {
				activeRunId = null;
				conversationId = progress.conversation_id || progress.result?.conversation_id || conversationId;
				await loadConversationList();
				return progress;
			}
			if (progress.status === "failed") {
				activeRunId = null;
				await loadConversationList();
				return progress;
			}
			if (progress.status === "missing") {
				throw new Error(__("Der Fortschritt des Assistentenlaufs ist nicht mehr verfügbar."));
			}
			progress = null;
			await wait(ASSISTANT_POLL_INTERVAL_MS);
		}
		if (generation !== pollGeneration) return null;
		throw new Error(__("Der Assistent arbeitet zu lange. Der Chat kann später erneut geöffnet werden."));
	};

	const clearChat = () => {
		pollGeneration += 1;
		activeRunId = null;
		conversationId = null;
		messagesEl.empty();
		renderResults([]);
		setComposerDisabled(false);
		conversationsEl.find(".hv-assistant-conversation").removeClass("active");
		mobileTitle.text(__("Neuer Chat"));
		closeMobilePanels();
		focusComposer();
	};

	const renderConversationList = (rows) => {
		conversationsEl.empty();
		if (!rows || !rows.length) {
			conversationsEl.html(`<div class="hv-assistant-empty">${__("Keine Chats")}</div>`);
			return;
		}
		rows.forEach((row) => {
			const button = $(`
				<button class="hv-assistant-conversation" type="button">
					<div class="hv-assistant-conversation-title"></div>
					<div class="hv-assistant-conversation-meta"></div>
				</button>
			`);
			button.toggleClass("active", row.name === conversationId);
			button.find(".hv-assistant-conversation-title").text(row.title || row.name);
			const engineLabel = row.engine === "mistral_basic"
				? __("Mistral Basic")
				: row.engine === "mistral_agents"
					? __("Mistral Agent")
					: __("Bestehend");
			const runLabel = row.active_run_id ? ` · ${__("laeuft")}` : "";
			button.find(".hv-assistant-conversation-meta").text(
				`${row.message_count || 0} ${__("Nachrichten")} · ${engineLabel}${runLabel}`
			);
			button.on("click", () => {
				closeMobilePanels();
				loadConversation(row.name);
			});
			conversationsEl.append(button);
		});
	};

	const loadConversationList = async () => {
		const response = await frappe.call({
			method: "hausverwaltung.hausverwaltung.services.assistant.list_conversations",
			args: { limit: 30 },
		});
		renderConversationList(response.message || []);
	};

	const loadConversation = async (name) => {
		const generation = ++pollGeneration;
		activeRunId = null;
		const response = await frappe.call({
			method: "hausverwaltung.hausverwaltung.services.assistant.get_conversation",
			args: { conversation_id: name },
		});
		if (generation !== pollGeneration) return;
		const data = response.message || {};
		conversationId = data.name || name;
		mobileTitle.text(data.title || __("Chat"));
		engineSelect.val(data.engine || "classic");
		const hasStoredModel = modelSelect
			.find("option")
			.toArray()
			.some((option) => option.value === data.assistant_model);
		if (data.assistant_model && hasStoredModel) {
			modelSelect.val(data.assistant_model);
		}
		messagesEl.empty();
		let lastMatches = [];
		(data.messages || []).forEach((message) => {
			addMessage(
				message.role === "user" ? "user" : "assistant",
				message.content || "",
				message.tool_calls || [],
				message.reasoning || "",
				message.mistral_usage || {}
			);
			if (message.matches && message.matches.length) {
				lastMatches = message.matches;
			}
		});
		renderResults(lastMatches);
		await loadConversationList();
		if (data.active_run_id && generation === pollGeneration) {
			activeRunId = data.active_run_id;
			setComposerDisabled(true);
			let initialProgress = null;
			try {
				const progressResponse = await frappe.call({
					method: "hausverwaltung.hausverwaltung.services.assistant_async.get_assistant_run_progress",
					args: { run_id: activeRunId },
				});
				initialProgress = progressResponse.message || {};
			} catch (error) {
				initialProgress = null;
			}
			if (generation !== pollGeneration) return;
			if (initialProgress?.user_message) {
				addMessage("user", initialProgress.user_message);
			}
			const pending = addMessage("assistant", initialProgress?.stage || __("Suche laeuft ..."));
			try {
				await pollAssistantRun(activeRunId, pending, generation, initialProgress);
			} catch (error) {
				if (generation === pollGeneration) {
					pending.className = "hv-assistant-message error";
					pending.textContent = errorText(error);
				}
			} finally {
				if (generation === pollGeneration) setComposerDisabled(false);
			}
			return;
		}
		setComposerDisabled(false);
		focusComposer();
	};

	const renderResults = (matches) => {
		resultsEl.empty();
		resultsCount.text((matches || []).length);
		if (!matches || !matches.length) {
			resultsEl.html(`<div class="hv-assistant-empty">${__("Keine Treffer")}</div>`);
			return;
		}
		matches.forEach((match) => {
			const card = $(`
				<div class="hv-assistant-result">
					<div class="hv-assistant-result-title"></div>
					<div class="hv-assistant-result-subtitle"></div>
					<div class="hv-assistant-result-meta"></div>
					<div class="hv-assistant-route-row"></div>
				</div>
			`);
			card.find(".hv-assistant-result-title").text(match.title || match.customer_name || match.customer || "");
			card.find(".hv-assistant-result-subtitle").text(match.subtitle || "");
			card.find(".hv-assistant-result-meta").text(match.mietvertrag || "");
			const routeRow = card.find(".hv-assistant-route-row");
			(match.routes || []).forEach((route) => {
				const btn = $(`<button class="btn btn-xs btn-default" type="button"></button>`);
				btn.text(route.label || route.doctype || __("Oeffnen"));
				btn.on("click", () => {
					closeMobilePanels();
					if (route.route) {
						frappe.set_route(route.route);
					} else if (route.doctype && route.name) {
						frappe.set_route("Form", route.doctype, route.name);
					}
				});
				routeRow.append(btn);
			});
			resultsEl.append(card);
		});
	};

	window.hvAssistantSend = async (rawMessage) => {
		const message = (rawMessage || "").trim();
		if (!message) return;
		closeMobilePanels();
		input.val("");
		addMessage("user", message);
		const pending = addMessage("assistant", __("Anfrage wird gestartet ..."));
		const generation = ++pollGeneration;
		setComposerDisabled(true);
		try {
			const response = await frappe.call({
				method: "hausverwaltung.hausverwaltung.services.assistant_async.start_assistant_run",
				args: {
					message,
					conversation_id: conversationId,
					model: modelSelect.val() || "default",
					engine: engineSelect.val() || "classic",
				},
			});
			const progress = response.message || {};
			conversationId = progress.conversation_id || conversationId;
			activeRunId = progress.run_id || null;
			if (!activeRunId) throw new Error(__("Der Assistentenlauf konnte nicht gestartet werden."));
			renderRunProgress(pending, progress);
			await loadConversationList();
			await pollAssistantRun(activeRunId, pending, generation, progress);
		} catch (err) {
			if (generation === pollGeneration) {
				pending.className = "hv-assistant-message error";
				pending.textContent = errorText(err);
			}
		} finally {
			if (generation === pollGeneration) {
				setComposerDisabled(false);
				focusComposer();
			}
		}
	};

	form.on("submit", (event) => {
		event.preventDefault();
		window.hvAssistantSend(input.val());
	});

	root.find(".hv-assistant-new").on("click", clearChat);
	engineSelect.on("change", clearChat);
	modelSelect.on("change", clearChat);

	resultsEl.html(`<div class="hv-assistant-empty">${__("Keine Treffer")}</div>`);
	const initialize = async () => {
		await loadAssistantModels();
		await loadConversationList();
	};
	initialize();
	focusComposer();
}
