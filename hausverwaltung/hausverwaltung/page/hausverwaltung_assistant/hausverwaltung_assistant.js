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
				grid-template-columns: minmax(0, 1fr) 360px;
				gap: 16px;
				max-width: 1320px;
				margin: 0 auto;
				padding: 18px;
			}
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
			.hv-assistant-results-title {
				font-weight: 600;
				font-size: 13px;
				text-transform: uppercase;
				color: #666;
				margin-bottom: 10px;
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
	const form = root.find(".hv-assistant-form");
	const input = root.find(".hv-assistant-input");

	const addMessage = (kind, text) => {
		const node = document.createElement("div");
		node.className = `hv-assistant-message ${kind}`;
		node.textContent = text;
		messagesEl.append(node);
		messagesEl.scrollTop(messagesEl[0].scrollHeight);
		return node;
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
				args: { message },
			});
			const data = response.message || {};
			pending.textContent = data.answer || __("Keine Antwort erhalten.");
			renderResults(data.matches || []);
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

	resultsEl.html(`<div class="hv-assistant-empty">${__("Keine Treffer")}</div>`);
	input.trigger("focus");
}
