"""Phase 8 Stufe 1b Re-Export: orchestrator wohnt jetzt in
process_engine.process_engine.integrations.temporal.orchestrator.

Dieses Modul existiert nur damit bestehende Imports
`from hausverwaltung.hausverwaltung.integrations.temporal.orchestrator import ...`
weiter laufen. Neuer Code sollte direkt aus process_engine importieren.
"""
from process_engine.process_engine.integrations.temporal.orchestrator import *  # noqa: F401,F403
