frappe.pages["sprachnotiz-aufnahme"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Sprachnotiz Aufnahme",
		single_column: true,
	});

	page.set_primary_action(__("Start Aufnahme"), () => startRecording(), "small");
	page.set_secondary_action(__("Abbrechen"), () => cancelRecording());

	const state = {
		recorder: null,
		stream: null,
		chunks: [],
		startedAt: null,
		stopping: false,
	};

	const body = $(`
		<div class="hv-sprachnotiz-page" style="max-width:900px;padding:24px 0;">
			<div style="border:1px solid #dfe3e8;border-radius:16px;padding:24px;background:linear-gradient(135deg,#fffdf7,#eef6ff);">
				<h3 style="margin-top:0;">Sprachnotiz direkt in ERPNext aufnehmen</h3>
				<p class="text-muted" style="margin-bottom:20px;">Start klicken, sprechen, dann Stop &amp; speichern. Transkription laeuft automatisch im Hintergrund.</p>
				<div class="form-group">
					<label class="control-label">Sprache</label>
					<input type="text" class="form-control hv-language" value="de">
				</div>
				<div class="form-group">
					<label class="control-label">Bezug Doctype (optional)</label>
					<input type="text" class="form-control hv-bezug-doctype" placeholder="z.B. Mieterwechsel">
				</div>
				<div class="form-group">
					<label class="control-label">Bezug Name (optional)</label>
					<input type="text" class="form-control hv-bezug-name" placeholder="z.B. VG-2026-00001">
				</div>
				<div class="hv-status alert alert-info">Bereit.</div>
				<div style="display:flex;gap:12px;flex-wrap:wrap;">
					<button class="btn btn-primary hv-start">Start Aufnahme</button>
					<button class="btn btn-danger hv-stop" disabled>Stop &amp; speichern</button>
					<button class="btn btn-default hv-cancel" disabled>Abbrechen</button>
				</div>
				<div class="hv-timer text-muted" style="margin-top:16px;"></div>
			</div>
		</div>
	`).appendTo(page.body);

	const statusEl = body.find(".hv-status");
	const timerEl = body.find(".hv-timer");
	const startBtn = body.find(".hv-start");
	const stopBtn = body.find(".hv-stop");
	const cancelBtn = body.find(".hv-cancel");

	const setStatus = (message, level = "info") => {
		statusEl.removeClass("alert-info alert-warning alert-success alert-danger").addClass(`alert-${level}`);
		statusEl.text(message);
	};

	const setButtons = ({ recording, busy }) => {
		startBtn.prop("disabled", recording || busy);
		stopBtn.prop("disabled", !recording || busy);
		cancelBtn.prop("disabled", !recording || busy);
	};

	const stopTracks = () => {
		(state.stream?.getTracks?.() || []).forEach((track) => track.stop());
		state.stream = null;
	};

	const reset = () => {
		state.recorder = null;
		state.chunks = [];
		state.startedAt = null;
		state.stopping = false;
		stopTracks();
		timerEl.text("");
		setButtons({ recording: false, busy: false });
	};

	const tick = () => {
		if (!state.startedAt) return;
		const elapsed = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
		const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
		const seconds = String(elapsed % 60).padStart(2, "0");
		timerEl.text(`Laufzeit ${minutes}:${seconds}`);
		if (state.recorder && state.recorder.state === "recording") {
			window.setTimeout(tick, 1000);
		}
	};

	const uploadRecording = async (blob) => {
		const formData = new FormData();
		formData.append("file", blob, `sprachnotiz-${Date.now()}.webm`);
		formData.append("sprache", body.find(".hv-language").val() || "de");
		formData.append("bezug_doctype", body.find(".hv-bezug-doctype").val() || "");
		formData.append("bezug_name", body.find(".hv-bezug-name").val() || "");

		const response = await window.fetch("/api/method/hausverwaltung.hausverwaltung.doctype.sprachnotiz.sprachnotiz.create_from_recording", {
			method: "POST",
			headers: {
				"X-Frappe-CSRF-Token": frappe.csrf_token,
			},
			body: formData,
			credentials: "same-origin",
		});
		const payload = await response.json();
		if (!response.ok || payload.exc) {
			throw new Error((payload._server_messages && JSON.parse(payload._server_messages)[0]) || payload.exc || "Upload fehlgeschlagen.");
		}
		return payload.message || {};
	};

	async function startRecording() {
		if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
			frappe.msgprint(__("Dieser Browser unterstuetzt keine direkte Audioaufnahme."));
			return;
		}

		try {
			state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			state.chunks = [];
			state.recorder = new MediaRecorder(state.stream, { mimeType: "audio/webm" });
			state.startedAt = Date.now();
			setButtons({ recording: true, busy: false });
			setStatus("Aufnahme laeuft.", "warning");
			tick();

			state.recorder.addEventListener("dataavailable", (event) => {
				if (event.data?.size) {
					state.chunks.push(event.data);
				}
			});

			state.recorder.addEventListener("stop", async () => {
				if (!state.stopping) {
					reset();
					setStatus("Aufnahme abgebrochen.", "info");
					return;
				}
				setButtons({ recording: false, busy: true });
				setStatus("Upload und Verarbeitung werden gestartet ...", "warning");
				try {
					const blob = new Blob(state.chunks, { type: "audio/webm" });
					const result = await uploadRecording(blob);
					reset();
					setStatus("Sprachnotiz gespeichert. Formular wird geoeffnet.", "success");
					if (result.sprachnotiz_name) {
						frappe.set_route("Form", "Sprachnotiz", result.sprachnotiz_name);
					}
				} catch (error) {
					reset();
					setStatus(error.message || "Upload fehlgeschlagen.", "danger");
				}
			});

			state.recorder.start(1000);
		} catch (error) {
			reset();
			setStatus(error.message || "Aufnahme konnte nicht gestartet werden.", "danger");
		}
	}

	function stopRecording() {
		if (!state.recorder || state.recorder.state !== "recording") {
			return;
		}
		state.stopping = true;
		state.recorder.stop();
	}

	function cancelRecording() {
		if (!state.recorder || state.recorder.state !== "recording") {
			reset();
			setStatus("Bereit.", "info");
			return;
		}
		state.stopping = false;
		state.recorder.stop();
	}

	startBtn.on("click", () => startRecording());
	stopBtn.on("click", () => stopRecording());
	cancelBtn.on("click", () => cancelRecording());
};
