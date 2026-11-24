(() => {
	const prefix = "hausverwaltung.hausverwaltung.doctype.wohnungsabnahme.";
	const args = Object.fromEntries(new URLSearchParams(window.location.search));
	const target = { mietvertrag: args.mietvertrag || "", richtung: args.richtung || "" };
	if (args.prozess) target.prozess = args.prozess;

	const el = (id) => document.getElementById(id);
	let initial;
	let state;
	let devices = [];
	let busy = false;
	let dirty = false;

	async function call(method, data, verb = "POST") {
		const search = verb === "GET" ? "?" + new URLSearchParams(data) : "";
		const options = { method: verb, headers: { Accept: "application/json" }, cache: "no-store" };
		if (verb === "POST") {
			options.headers["X-Frappe-CSRF-Token"] = document.querySelector('meta[name="csrf-token"]').content;
			if (data instanceof FormData) {
				options.body = data;
			} else {
				options.headers["Content-Type"] = "application/json";
				options.body = JSON.stringify(data);
			}
		}
		const response = await fetch("/api/method/" + prefix + method + search, options);
		const result = await response.json();
		if (!response.ok || result.exc) {
			let message = "Der Vorgang ist fehlgeschlagen. Bitte prüfen Sie die Verbindung und versuchen Sie es erneut.";
			if (result._server_messages) {
				const messages = JSON.parse(result._server_messages).map((item) => JSON.parse(item).message);
				const last = new DOMParser().parseFromString(messages.at(-1), "text/html");
				message = last.body.textContent || message;
			}
			throw new Error(message);
		}
		return result.message;
	}

	function status(text, error = false) {
		el("status").textContent = text;
		el("status").classList.toggle("error", error);
	}

	function node(tag, text, parent) {
		const child = document.createElement(tag);
		if (text) child.textContent = text;
		parent.append(child);
		return child;
	}

	function input(parent, label, attrs, value, update) {
		const wrapper = node("label", label, parent);
		const field = node(attrs.rows ? "textarea" : "input", "", wrapper);
		for (const [key, attr] of Object.entries(attrs)) field.setAttribute(key, attr);
		field.value = value ?? "";
		if (update) field.addEventListener("input", () => {
			update(field.value);
			dirty = true;
		});
		return field;
	}

	function button(parent, label, action) {
		const item = node("button", label, parent);
		item.type = "button";
		item.addEventListener("click", action);
		return item;
	}

	function drawRooms(editable) {
		const section = el("rooms");
		section.replaceChildren();
		for (const room of state.rooms) {
			const row = node("div", "", section);
			row.className = "entry";
			input(row, "Raum", { maxlength: 200 }, room.label, (value) => room.label = value);
			input(row, "Zustand", { rows: 2, maxlength: 4000 }, room.condition, (value) => room.condition = value);
			input(row, "Mängel", { rows: 2, maxlength: 4000 }, room.defects, (value) => room.defects = value);
			const photos = node("div", "", row);
			photos.className = "photos";
			for (const photo of room.photos) {
				const figure = node("figure", "", photos);
				const link = node("a", "", figure);
				link.href = photo.url;
				link.target = "_blank";
				link.rel = "noopener";
				const img = node("img", "", link);
				img.alt = "Raumfoto";
				img.src = photo.url;
				img.loading = "lazy";
				if (editable) button(figure, "Foto entfernen", () => run(async () => {
					await save();
					state = await call("wohnungsabnahme.remove_photo", {
						name: state.name, stand: state.stand, room_id: room.id, file_name: photo.name,
					});
					draw();
					status("Foto entfernt.");
				}));
			}
			if (!editable) continue;
			const upload = input(row, "Raumfoto aufnehmen oder auswählen", {
				type: "file", accept: "image/jpeg,image/png,image/webp", capture: "environment",
			});
			upload.addEventListener("change", () => {
				const photo = upload.files[0];
				if (!photo) return;
				run(async () => {
					await save();
					const data = new FormData();
					for (const [key, value] of Object.entries({
						name: state.name, stand: state.stand, room_id: room.id, photo,
					})) data.append(key, value);
					state = await call("wohnungsabnahme.upload_photo", data);
					draw();
					status("Entwurf und Foto gespeichert.");
				});
			});
			if (!room.photos.length) button(row, "Raum entfernen", () => {
				state.rooms = state.rooms.filter((item) => item !== room);
				dirty = true;
				drawRooms(true);
			});
		}
	}

	function drawKeys(editable) {
		const section = el("keys");
		section.replaceChildren();
		for (const key of state.keys) {
			const row = node("div", "", section);
			row.className = "entry";
			input(row, "Schlüsselart", { maxlength: 200 }, key.label, (value) => key.label = value);
			input(row, "Anzahl", { inputmode: "numeric", maxlength: 6, pattern: "[0-9]*" }, key.count, (value) => key.count = value);
			if (editable) button(row, "Schlüsselart entfernen", () => {
				state.keys = state.keys.filter((item) => item !== key);
				dirty = true;
				drawKeys(true);
			});
		}
	}

	async function fetchDevices() {
		devices = await call("wohnungsabnahme.meters", {
			mietvertrag: target.mietvertrag, termin: state.termin,
		}, "GET");
	}

	function drawMeters(editable) {
		const section = el("meters");
		section.replaceChildren();
		const available = new Map(devices.map((device) => [device.name, device]));
		if (editable) {
			for (const device of devices) {
				if (!state.meters.some((reading) => reading.name === device.name)) {
					state.meters.push({ name: device.name, date: state.termin, value: "" });
				}
			}
		}
		if (!state.meters.length) node("p", "Keine Zähler zugeordnet.", section);
		for (const reading of state.meters) {
			const row = node("div", "", section);
			row.className = "entry";
			const device = available.get(reading.name);
			node("h3", device ? device.zaehlerart + " " + device.zaehlernummer : reading.name, row);
			if (device?.standort_beschreibung) node("p", device.standort_beschreibung, row);
			input(row, "Ablesedatum", { type: "date" }, reading.date, (value) => reading.date = value);
			input(row, "Zählerstand", { inputmode: "decimal", maxlength: 30 }, reading.value, (value) => reading.value = value);
			if (editable && !device) button(row, "Ablesung entfernen", () => {
				state.meters = state.meters.filter((item) => item !== reading);
				dirty = true;
				drawMeters(true);
			});
		}
	}

	function localUrl(path) {
		const url = new URL(path, window.location.origin);
		if (url.origin !== window.location.origin) throw new Error("Ungültige Datei-Adresse.");
		return url.href;
	}

	function showResult() {
		el("result").hidden = !state.protokoll;
		if (!state.protokoll) return;
		el("pdf").href = localUrl(state.protokoll);
		if (state.paperless_link && /^https?:\/\//i.test(state.paperless_link)) {
			el("archive-link").href = state.paperless_link;
			el("archive").hidden = false;
		}
		const steps = el("steps");
		steps.replaceChildren();
		for (const process of initial.steps) {
			const row = node("div", "", steps);
			row.className = "step";
			const link = node("a", process.label, row);
			link.href = "/app/prozess-instanz/" + encodeURIComponent(process.name);
			if (process.editable) button(row, "Für „Abnahmeprotokoll“ auswählen", () => run(async () => {
				await call("process.select_protocol", { name: state.name, prozess: process.name });
				window.location.assign(link.href);
			}));
		}
	}

	function draw() {
		const editable = initial.editable && !state.protokoll;
		el("handover").hidden = false;
		el("appointment").value = state.termin;
		el("keys-heading").textContent = target.richtung === "Einzug" ? "Ausgegebene Schlüssel" : "Zurückgegebene Schlüssel";
		drawRooms(editable);
		drawKeys(editable);
		drawMeters(editable);
		el("draft-actions").hidden = !editable;
		markBusy(busy);
		showResult();
	}

	function markBusy(value) {
		busy = value;
		el("inputs").disabled = busy || !initial?.editable || !!state?.protokoll;
		for (const id of ["save", "complete"]) el(id).disabled = busy;
		el("handover").setAttribute("aria-busy", String(busy));
	}

	async function run(action) {
		if (busy) return;
		markBusy(true);
		try {
			await action();
		} catch (error) {
			status(error.message, true);
		} finally {
			markBusy(false);
		}
	}

	async function save() {
		if (state.name && !dirty) return;
		if (!state.termin) throw new Error("Bitte das Abnahmedatum auswählen.");
		state = await call("wohnungsabnahme.save_draft", {
			mietvertrag: target.mietvertrag, richtung: target.richtung, termin: state.termin,
			inhalt: JSON.stringify({ rooms: state.rooms, keys: state.keys, meters: state.meters }),
			stand: state.stand,
		});
		dirty = false;
		draw();
	}

	el("appointment").addEventListener("change", () => {
		const previous = state.termin;
		state.termin = el("appointment").value;
		if (!state.termin) return;
		state.meters = state.meters.filter((reading) => reading.value !== "" || reading.date !== previous);
		dirty = true;
		run(async () => {
			await fetchDevices();
			drawMeters(true);
		});
	});
	el("add-room").addEventListener("click", () => {
		state.rooms.push({ id: crypto.randomUUID(), label: "", condition: "", defects: "", photos: [] });
		dirty = true;
		drawRooms(true);
		el("rooms").lastElementChild.querySelector("input").focus();
	});
	el("add-key").addEventListener("click", () => {
		state.keys.push({ label: "", count: "" });
		dirty = true;
		drawKeys(true);
		el("keys").lastElementChild.querySelector("input").focus();
	});
	el("handover").addEventListener("submit", (event) => {
		event.preventDefault();
		run(async () => {
			await save();
			draw();
			status(state.klaerfall || "Entwurf gespeichert.", !!state.klaerfall);
		});
	});
	el("complete").addEventListener("click", () => {
		if (!el("handover").reportValidity()) return;
		run(async () => {
			await save();
			status("Protokoll wird erstellt …");
			state = await call("wohnungsabnahme.complete", { name: state.name, stand: state.stand });
			draw();
			status(state.klaerfall ? "Klärfall\n" + state.klaerfall : "Wohnungsabnahme abgeschlossen.", !!state.klaerfall);
			if (state.protokoll) el("result").scrollIntoView();
		});
	});
	window.addEventListener("beforeunload", (event) => {
		if (dirty) event.preventDefault();
	});

	run(async () => {
		initial = await call("wohnungsabnahme.load", target, "GET");
		el("direction").textContent = "· " + target.richtung;
		el("property").textContent = initial.wohnung_label + " · Mietvertrag " + initial.vertrag;
		el("back").href = target.prozess
			? "/app/prozess-instanz/" + encodeURIComponent(target.prozess)
			: "/app/mietvertrag/" + encodeURIComponent(initial.vertrag);
		state = initial.draft || { termin: initial.termin, stand: 0, rooms: [], keys: [], meters: [] };
		await fetchDevices();
		draw();
		status(state.klaerfall ? "Klärfall\n" + state.klaerfall
			: state.protokoll ? "Wohnungsabnahme abgeschlossen." : state.name ? "Gespeicherter Entwurf" : "", !!state.klaerfall);
	});
})();
