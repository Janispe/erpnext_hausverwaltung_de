from .engine import (
	BACKEND_LOCAL,
	BACKEND_TEMPORAL,
	STATUS_ABGESCHLOSSEN,
	STATUS_ABGESCHLOSSEN_BYPASS,
	STATUS_ABSCHLUSSPRUEFUNG,
	STATUS_IN_BEARBEITUNG,
	BaseProcessDocument,
	CompletionCheckResult,
	ProcessEngine,
	ProcessRuntimeConfig,
	ProcessTrigger,
	get_process_runtime_config,
	register_process_runtime,
)


def ensure_process_runtimes_registered() -> None:
	"""Importiert alle Runtime-Definitionsmodule, damit register_process_runtime()
	in jedem Web-Worker-Prozess garantiert aufgerufen wurde. Sonst koennte
	_PROCESS_RUNTIMES je nach Import-Reihenfolge leer sein.

	Idempotent: register_process_runtime ueberschreibt nur, und get_*_runtime
	hat einen Cache am _RUNTIME-Modul-Level.
	"""
	from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel import get_mieterwechsel_runtime

	get_mieterwechsel_runtime()
	# Future: weitere Definitions hier ergaenzen (eigentuemerwechsel, mahnwesen, ...)


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
	"ProcessRuntimeConfig",
	"ProcessTrigger",
	"ensure_process_runtimes_registered",
	"get_process_runtime_config",
	"register_process_runtime",
]
