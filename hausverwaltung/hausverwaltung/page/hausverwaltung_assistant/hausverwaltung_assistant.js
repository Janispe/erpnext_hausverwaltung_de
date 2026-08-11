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
			<div class="hv-assistant-shell">
				<div class="hv-assistant-conversations">
					<div class="hv-assistant-conversations-head">
						<div class="hv-assistant-results-title">${__("Chats")}</div>
						<button class="btn btn-xs btn-default hv-assistant-new" type="button">${__("Neu")}</button>
					</div>
					<div class="hv-assistant-conversation-list"></div>
				</div>
				<div class="hv-assistant-main">
					<div class="hv-assistant-messages" aria-live="polite"></div>
					<form class="hv-assistant-form">
						<input class="hv-assistant-input" type="search" autocomplete="off" placeholder="${__("Frage stellen oder Stammdaten suchen")}">
						<select class="hv-assistant-engine" aria-label="${__("Engine")}" title="${__("Ausfuehrungsart fuer diesen Chat")}">
							<option value="classic">${__("Bestehend")}</option>
							<option value="mistral_agents">${__("Mistral Agents (Prototyp)")}</option>
						</select>
						<select class="hv-assistant-model" aria-label="${__("Modell")}" title="${__("Modell fuer diese Anfrage")}">
							<option value="default">${__("Standardmodell")}</option>
						</select>
						<button class="btn btn-primary hv-assistant-submit" type="submit">${__("Senden")}</button>
					</form>
				</div>
				<div class="hv-assistant-results">
					<div class="hv-assistant-results-title">${__("Treffer")}</div>
					<div class="hv-assistant-results-list"></div>
				</div>
			</div>
		</div>
		<style>
			.hv-assistant {
				margin: -15px -15px 0;
				min-height: calc(100vh - 110px);
				background: #f7f7f5;
				color: #1f2328;
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
			}
			.hv-assistant-messages {
				padding: 18px;
				overflow: auto;
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
				.hv-assistant-shell {
					grid-template-columns: 1fr;
				}
				.hv-assistant-conversations,
				.hv-assistant-main,
				.hv-assistant-results {
					min-height: auto;
				}
			}
			@media (max-width: 560px) {
				.hv-assistant-shell {
					padding: 10px;
				}
				.hv-assistant-form {
					grid-template-columns: 1fr;
				}
			}
		</style>
	`);

	const messagesEl = root.find(".hv-assistant-messages");
	const resultsEl = root.find(".hv-assistant-results-list");
	const conversationsEl = root.find(".hv-assistant-conversation-list");
	const form = root.find(".hv-assistant-form");
	const input = root.find(".hv-assistant-input");
	const engineSelect = root.find(".hv-assistant-engine");
	const modelSelect = root.find(".hv-assistant-model");
	let conversationId = null;

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
			appendAnalysisRow(item, __("Werkzeug"), step.tool);
			appendAnalysisRow(item, __("Filter"), step.filters);
			appendAnalysisRow(item, __("Berechnung"), aggregationLabel(step.aggregation));
			appendAnalysisRow(item, __("Ergebnis"), aggregationResultLabel(step.aggregation_result));
			appendAnalysisRow(item, __("Treffer"), step.result_count);
			appendAnalysisRow(item, __("Sortierung"), step.order_by);
			const error = toolCalls[index]?.error;
			if (error) appendAnalysisRow(item, __("Fehler"), error.message || error);
			(step.warnings || []).forEach((warning) => {
				const warningNode = document.createElement("div");
				warningNode.className = "hv-assistant-analysis-warning";
				warningNode.textContent = warning;
				item.append(warningNode);
			});
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

	const addMessage = (kind, text, toolCalls, reasoning) => {
		const node = document.createElement("div");
		node.className = `hv-assistant-message ${kind}`;
		node.textContent = textFromAny(text);
		appendReasoning(node, reasoning);
		appendAnalysis(node, toolCalls);
		appendToolCalls(node, toolCalls);
		messagesEl.append(node);
		messagesEl.scrollTop(messagesEl[0].scrollHeight);
		return node;
	};

	const clearChat = () => {
		conversationId = null;
		messagesEl.empty();
		renderResults([]);
		conversationsEl.find(".hv-assistant-conversation").removeClass("active");
		input.trigger("focus");
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
			const engineLabel = row.engine === "mistral_agents" ? __("Mistral Agent") : __("Bestehend");
			button.find(".hv-assistant-conversation-meta").text(
				`${row.message_count || 0} ${__("Nachrichten")} · ${engineLabel}`
			);
			button.on("click", () => loadConversation(row.name));
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
		const response = await frappe.call({
			method: "hausverwaltung.hausverwaltung.services.assistant.get_conversation",
			args: { conversation_id: name },
		});
		const data = response.message || {};
		conversationId = data.name || name;
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
				message.reasoning || ""
			);
			if (message.matches && message.matches.length) {
				lastMatches = message.matches;
			}
		});
		renderResults(lastMatches);
		await loadConversationList();
		input.trigger("focus");
	};

	const renderResults = (matches) => {
		resultsEl.empty();
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
		input.val("");
		addMessage("user", message);
		const pending = addMessage("assistant", __("Suche laeuft ..."));
		form.find("button, input, select").prop("disabled", true);
		try {
			const response = await frappe.call({
				method: "hausverwaltung.hausverwaltung.services.assistant.ask",
				args: {
					message,
					conversation_id: conversationId,
					model: modelSelect.val() || "default",
					engine: engineSelect.val() || "classic",
				},
			});
			const data = response.message || {};
			conversationId = data.conversation_id || conversationId;
			pending.textContent = textFromAny(data.answer) || __("Keine Antwort erhalten.");
			appendReasoning(pending, data.reasoning || "");
			appendAnalysis(pending, data.tool_calls || []);
			appendToolCalls(pending, data.tool_calls || []);
			renderResults(data.matches || []);
			await loadConversationList();
		} catch (err) {
			pending.className = "hv-assistant-message error";
			pending.textContent = errorText(err);
		} finally {
			form.find("button, input, select").prop("disabled", false);
			input.trigger("focus");
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
	input.trigger("focus");
}
