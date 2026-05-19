"""Phase 8 Stufe 1a (Uebergang): die Engine wohnt jetzt in
`process_engine.process_engine.processes`. Dieses Modul ist ein duenner
Re-Export-Wrapper, damit bestehende hausverwaltung-Imports
(`from hausverwaltung.hausverwaltung.processes import ...`) weiterhin laufen,
bis Stufe 2 (Mieterwechsel nach peters) die letzten Verbraucher umgestellt
hat.

Nach Stufe 2 kann dieses Modul komplett entfernt werden.
"""
from process_engine.process_engine.processes import (
	BACKEND_LOCAL,
	BACKEND_TEMPORAL,
	STATUS_ABGESCHLOSSEN,
	STATUS_ABGESCHLOSSEN_BYPASS,
	STATUS_ABSCHLUSSPRUEFUNG,
	STATUS_IN_BEARBEITUNG,
	BaseProcessDocument,
	CompletionCheckResult,
	ProcessEngine,
	ProcessPluginRegistry,
	ProcessRuntimeConfig,
	ProcessTrigger,
	ensure_process_runtimes_registered,
	get_process_runtime_config,
	get_runtime_config_for_typ,
	register_process_runtime,
)

__all__ = [
	"BACKEND_LOCAL",
	"BACKEND_TEMPORAL",
	"STATUS_ABGESCHLOSSEN",
	"STATUS_ABGESCHLOSSEN_BYPASS",
	"STATUS_ABSCHLUSSPRUEFUNG",
	"STATUS_IN_BEARBEITUNG",
	"BaseProcessDocument",
	"CompletionCheckResult",
	"ProcessEngine",
	"ProcessPluginRegistry",
	"ProcessRuntimeConfig",
	"ProcessTrigger",
	"ensure_process_runtimes_registered",
	"get_process_runtime_config",
	"get_runtime_config_for_typ",
	"register_process_runtime",
]
