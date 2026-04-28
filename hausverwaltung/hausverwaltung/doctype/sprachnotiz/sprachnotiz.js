frappe.ui.form.on("Sprachnotiz", {
	refresh(frm) {
		try {
			render_audio_player(frm);
		} catch (error) {
			console.error("Sprachnotiz player render failed", error);
			render_audio_player_fallback(frm, error);
		}
		render_intro(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(__("Aufnahmeseite"), () => {
				frappe.set_route("sprachnotiz-aufnahme");
			}, __("Aktionen"));
		}

		const status = (frm.doc.status || "").trim();
		if (frm.is_new()) {
			return;
		}
		if (status === "Audio gespeichert" || status === "Fehler") {
			frm.add_custom_button(__("Verarbeitung erneut starten"), () => {
				frappe.call({
					method: "hausverwaltung.hausverwaltung.doctype.sprachnotiz.sprachnotiz.retry_processing",
					args: { docname: frm.doc.name },
					freeze: true,
				}).then(() => frm.reload_doc());
			}, __("Aktionen"));
		}
		if (status === "Teilweise verarbeitet" || status === "Fehler") {
			frm.add_custom_button(__("Ollama erneut versuchen"), () => {
				frappe.call({
					method: "hausverwaltung.hausverwaltung.doctype.sprachnotiz.sprachnotiz.retry_ollama_enrichment",
					args: { docname: frm.doc.name },
					freeze: true,
				}).then(() => frm.reload_doc());
			}, __("Aktionen"));
		}
	},
});

frappe.ui.form.on("Sprachnotiz Segment", {
	zugeordnetes_todo(frm, cdt, cdn) {
		save_segment_mapping(frm, cdt, cdn);
	},
	zugeordnete_aufgabe(frm, cdt, cdn) {
		save_segment_mapping(frm, cdt, cdn);
	},
});

function save_segment_mapping(frm, cdt, cdn) {
	if (frm.is_new()) {
		return;
	}
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || !row.name) {
		return;
	}
	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.sprachnotiz.sprachnotiz.link_segment",
		args: {
			docname: frm.doc.name,
			segment_name: row.name,
			todo: row.zugeordnetes_todo || "",
			aufgabe: row.zugeordnete_aufgabe || "",
		},
	});
}

const HV_WAVESURFER_URL = "https://cdn.jsdelivr.net/npm/wavesurfer.js@7/dist/wavesurfer.min.js";

function render_audio_player(frm) {
	if (frm.__hvWaveSurfer && typeof frm.__hvWaveSurfer.destroy === "function") {
		try {
			frm.__hvWaveSurfer.destroy();
		} catch (error) {
			// ignore stale frontend instances during rerender
		}
		frm.__hvWaveSurfer = null;
	}

	const field = frm.get_field("player_html");
	if (!field || !field.$wrapper) {
		return;
	}

	const audioUrl = (frm.doc.audio_file || "").trim();
	if (!audioUrl) {
		field.$wrapper.html('<div class="text-muted" style="padding:8px 0;">Noch keine Aufnahme vorhanden.</div>');
		return;
	}

	const segments = (frm.doc.segmente || [])
		.map((row) => ({
			name: row.name,
			start: toInt(row.start_ms || 0) / 1000,
			end: toInt(row.end_ms || 0) / 1000,
			text: row.text || "",
			task: toInt(row.ist_task_vorschlag || 0) === 1,
		}))
		.filter((row) => row.text);

	const wrapper = field.$wrapper;
	const rootId = `hv-sprachnotiz-player-${frm.doc.name || "new"}`;
	wrapper.html(`
		<div id="${rootId}" style="border:1px solid #dfe3e8;border-radius:16px;padding:18px;background:linear-gradient(180deg,#fffef8,#f7fbff);">
			<div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
				<div>
					<div style="font-weight:600;">Aufnahme anhören</div>
					<div class="text-muted hv-player-state">${escapeHtml(buildStatusText(frm))}</div>
				</div>
				<div class="hv-player-time text-muted">00:00</div>
			</div>
			<div class="hv-player-controls" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
				<button type="button" class="btn btn-primary btn-sm hv-play-toggle">Abspielen</button>
				<a class="btn btn-default btn-sm" href="${escapeHtml(audioUrl)}" target="_blank" rel="noopener noreferrer">Audio öffnen</a>
			</div>
			<div class="hv-wave" style="min-height:80px;"></div>
			<div class="hv-audio-fallback" style="margin-top:12px;display:none;">
				<audio controls preload="metadata" src="${escapeHtml(audioUrl)}" style="width:100%;"></audio>
			</div>
			<div class="hv-transcript" style="margin-top:16px;max-height:260px;overflow:auto;border-top:1px solid #eceff3;padding-top:12px;"></div>
			<div class="hv-meta-note text-muted" style="margin-top:10px;"></div>
		</div>
	`);

	const root = wrapper.find(`#${rootId}`);
	const transcriptEl = root.find(".hv-transcript");
	const playerStateEl = root.find(".hv-player-state");
	const playerTimeEl = root.find(".hv-player-time");
	const noteEl = root.find(".hv-meta-note");
	const playToggle = root.find(".hv-play-toggle");
	const waveEl = root.find(".hv-wave").get(0);
	const fallbackWrap = root.find(".hv-audio-fallback");
	const fallbackAudio = fallbackWrap.find("audio").get(0);
	let activeSegmentIndex = -1;
	let usingFallbackPlayer = false;

	transcriptEl.html(
		segments.length
			? segments
					.map(
						(segment, index) => `
				<button type="button" class="btn btn-default btn-xs hv-segment" data-index="${index}" style="display:block;width:100%;text-align:left;margin-bottom:8px;padding:10px 12px;border-radius:12px;border:1px solid #e4e8ee;background:${segment.task ? "#fff8e1" : "#ffffff"};">
					<div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
						<span style="font-weight:600;">${formatSeconds(segment.start)} - ${formatSeconds(segment.end)}</span>
						${segment.task ? '<span class="label label-warning">Task</span>' : ""}
					</div>
					<div style="margin-top:6px;white-space:normal;">${escapeHtml(segment.text)}</div>
				</button>`
					)
					.join("")
			: '<div class="text-muted">Noch keine Segmente vorhanden.</div>'
	);
	noteEl.text(buildStatusDetail(frm));

	const updateActiveSegment = (currentTime) => {
		const nextIndex = segments.findIndex((segment) => currentTime >= segment.start && currentTime <= segment.end);
		if (nextIndex === activeSegmentIndex) {
			playerTimeEl.text(formatSeconds(currentTime));
			return;
		}
		activeSegmentIndex = nextIndex;
		transcriptEl.find(".hv-segment").each(function (buttonIndex) {
			const button = $(this);
			const isActive = buttonIndex === activeSegmentIndex;
			button.css({
				borderColor: isActive ? "#2f6fed" : "#e4e8ee",
				background: isActive ? "#eaf2ff" : segments[buttonIndex]?.task ? "#fff8e1" : "#ffffff",
				boxShadow: isActive ? "0 0 0 2px rgba(47,111,237,0.12)" : "none",
			});
			if (isActive) {
				button[0].scrollIntoView({ block: "nearest", behavior: "smooth" });
			}
		});
		playerTimeEl.text(formatSeconds(currentTime));
	};

	const bindTranscriptClicks = (seekFn) => {
		transcriptEl.find(".hv-segment").on("click", function () {
			const index = toInt($(this).data("index"));
			const segment = segments[index];
			if (!segment) {
				return;
			}
			seekFn(segment.start);
		});
	};

	const enableFallback = () => {
		usingFallbackPlayer = true;
		fallbackWrap.show();
		playerStateEl.text("Nativer Audio-Player aktiv.");
		playToggle.text("Abspielen");
		playToggle.off("click").on("click", () => {
			if (fallbackAudio.paused) {
				void fallbackAudio.play();
			} else {
				fallbackAudio.pause();
			}
		});
		fallbackAudio.addEventListener("play", () => playToggle.text("Pause"));
		fallbackAudio.addEventListener("pause", () => playToggle.text("Abspielen"));
		fallbackAudio.addEventListener("ended", () => playToggle.text("Abspielen"));
		bindTranscriptClicks((seconds) => {
			fallbackAudio.currentTime = seconds;
			void fallbackAudio.play();
		});
		fallbackAudio.addEventListener("timeupdate", () => updateActiveSegment(fallbackAudio.currentTime || 0));
	};

	loadWaveSurfer()
		.then((WaveSurfer) => {
			if (!WaveSurfer || !waveEl) {
				enableFallback();
				return;
			}
			const wavesurfer = WaveSurfer.create({
				container: waveEl,
				url: audioUrl,
				waveColor: "#c8d8ff",
				progressColor: "#2f6fed",
				cursorColor: "#15346a",
				barWidth: 2,
				barGap: 1,
				height: 88,
				normalize: true,
			});
			frm.__hvWaveSurfer = wavesurfer;
			playerStateEl.text("Waveform-Player aktiv.");
			playToggle.text("Abspielen");
			playToggle.off("click").on("click", () => {
				void wavesurfer.playPause();
			});
			wavesurfer.on("timeupdate", (currentTime) => updateActiveSegment(currentTime || 0));
			wavesurfer.on("interaction", () => updateActiveSegment(wavesurfer.getCurrentTime() || 0));
			wavesurfer.on("ready", () => updateActiveSegment(0));
			wavesurfer.on("play", () => playToggle.text("Pause"));
			wavesurfer.on("pause", () => playToggle.text("Abspielen"));
			wavesurfer.on("finish", () => playToggle.text("Abspielen"));
			bindTranscriptClicks((seconds) => {
				wavesurfer.setTime(seconds);
				void wavesurfer.play();
			});
		})
		.catch(() => {
			enableFallback();
		});
}

function render_audio_player_fallback(frm, error) {
	const field = frm.get_field("player_html");
	if (!field || !field.$wrapper) {
		return;
	}

	const audioUrl = (frm.doc.audio_file || "").trim();
	const message = error && error.message ? `Player konnte nicht vollständig geladen werden: ${error.message}` : "";
	field.$wrapper.html(`
		<div style="border:1px solid #dfe3e8;border-radius:16px;padding:18px;background:#fffef8;">
			<div style="font-weight:600;margin-bottom:6px;">Aufnahme anhören</div>
			<div class="text-muted" style="margin-bottom:12px;">${escapeHtml(buildStatusText(frm))}</div>
			${audioUrl ? `
				<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
					<a class="btn btn-default btn-sm" href="${escapeHtml(audioUrl)}" target="_blank" rel="noopener noreferrer">Audio öffnen</a>
				</div>
				<audio controls preload="metadata" src="${escapeHtml(audioUrl)}" style="width:100%;"></audio>
			` : '<div class="text-muted">Noch keine Aufnahme vorhanden.</div>'}
			<div class="text-muted" style="margin-top:12px;">${escapeHtml(buildStatusDetail(frm))}</div>
			${message ? `<div class="text-warning" style="margin-top:8px;">${escapeHtml(message)}</div>` : ""}
		</div>
	`);
}

function loadWaveSurfer() {
	if (window.WaveSurfer) {
		return Promise.resolve(window.WaveSurfer);
	}
	if (window.__hvWaveSurferPromise) {
		return window.__hvWaveSurferPromise;
	}
	window.__hvWaveSurferPromise = new Promise((resolve, reject) => {
		const script = document.createElement("script");
		script.src = HV_WAVESURFER_URL;
		script.async = true;
		script.onload = () => resolve(window.WaveSurfer || null);
		script.onerror = reject;
		document.head.appendChild(script);
	});
	return window.__hvWaveSurferPromise;
}

function render_intro(frm) {
	const status = buildStatusText(frm);
	const detail = buildStatusDetail(frm);
	if (status || detail) {
		const parts = [status, detail].filter(Boolean);
		frm.set_intro(parts.join(" "), statusLevel(frm));
		return;
	}
	frm.set_intro("");
}

function formatSeconds(value) {
	const total = Math.max(0, Math.floor(value || 0));
	const minutes = String(Math.floor(total / 60)).padStart(2, "0");
	const seconds = String(total % 60).padStart(2, "0");
	return `${minutes}:${seconds}`;
}

function buildStatusText(frm) {
	const status = (frm.doc.status || "").trim();
	if (status === "Audio gespeichert") {
		return "Audio ist gespeichert. Transkription wird vorbereitet.";
	}
	if (status === "Transkription laeuft") {
		return "Transkription laeuft.";
	}
	if (status === "Teilweise verarbeitet") {
		return "Audio und Transkript sind verfuegbar. Ollama-Nachverarbeitung fehlt noch oder ist deaktiviert.";
	}
	if (status === "Fehler") {
		return `Verarbeitung fehlgeschlagen: ${(frm.doc.transkript_fehler || frm.doc.temporal_last_error || "").trim() || "Unbekannter Fehler"}`;
	}
	return "Bereit.";
}

function buildStatusDetail(frm) {
	const status = (frm.doc.status || "").trim();
	if (status === "Audio gespeichert") {
		return "Du kannst die Aufnahme bereits anhoeren. Das Transkript folgt, sobald Whisper durchgelaufen ist.";
	}
	if (status === "Teilweise verarbeitet") {
		return "Die Aufnahme bleibt voll nutzbar. Nur Kurzfassung und Task-Vorschlaege warten noch auf Ollama.";
	}
	if (status === "Fehler") {
		return "Die Aufnahme ist gespeichert. Ueber 'Verarbeitung erneut starten' kannst du den Lauf wieder anstoßen.";
	}
	return "";
}

function statusLevel(frm) {
	const status = (frm.doc.status || "").trim();
	if (status === "Fehler") {
		return "red";
	}
	if (status === "Teilweise verarbeitet") {
		return "orange";
	}
	if (status === "Fertig") {
		return "green";
	}
	return "blue";
}

function toInt(value) {
	const parsed = Number.parseInt(value, 10);
	return Number.isFinite(parsed) ? parsed : 0;
}

function escapeHtml(value) {
	const text = value == null ? "" : String(value);
	if (frappe?.utils && typeof frappe.utils.escape_html === "function") {
		return frappe.utils.escape_html(text);
	}
	const node = document.createElement("div");
	node.textContent = text;
	return node.innerHTML;
}
