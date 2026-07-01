frappe.pages["hausverwaltung-assistant"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Mieter-Assistent"),
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
						<input class="hv-assistant-input" type="search" autocomplete="off" placeholder="${__("Mieter, Wohnung oder Immobilie suchen")}">
						<button class="btn btn-primary hv-assistant-submit" type="submit">${__("Suchen")}</button>
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
				grid-template-columns: minmax(0, 1fr) auto;
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
	let conversationId = null;

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

	const addMessage = (kind, text, toolCalls) => {
		const node = document.createElement("div");
		node.className = `hv-assistant-message ${kind}`;
		node.textContent = text;
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
			button.find(".hv-assistant-conversation-meta").text(`${row.message_count || 0} ${__("Nachrichten")}`);
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
		messagesEl.empty();
		let lastMatches = [];
		(data.messages || []).forEach((message) => {
			addMessage(
				message.role === "user" ? "user" : "assistant",
				message.content || "",
				message.tool_calls || []
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
		form.find("button, input").prop("disabled", true);
		try {
			const response = await frappe.call({
				method: "hausverwaltung.hausverwaltung.services.assistant.ask",
				args: { message, conversation_id: conversationId },
			});
			const data = response.message || {};
			conversationId = data.conversation_id || conversationId;
			pending.textContent = data.answer || __("Keine Antwort erhalten.");
			appendToolCalls(pending, data.tool_calls || []);
			renderResults(data.matches || []);
			await loadConversationList();
		} catch (err) {
			const text = err?._server_messages
				? JSON.parse(err._server_messages).map((m) => JSON.parse(m).message).join("\n")
				: (err.message || String(err));
			pending.className = "hv-assistant-message error";
			pending.textContent = text;
		} finally {
			form.find("button, input").prop("disabled", false);
			input.trigger("focus");
		}
	};

	form.on("submit", (event) => {
		event.preventDefault();
		window.hvAssistantSend(input.val());
	});

	root.find(".hv-assistant-new").on("click", clearChat);

	resultsEl.html(`<div class="hv-assistant-empty">${__("Keine Treffer")}</div>`);
	loadConversationList();
	input.trigger("focus");
}
