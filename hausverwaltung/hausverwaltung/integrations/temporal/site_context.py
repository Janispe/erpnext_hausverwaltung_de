"""Phase 8 Stufe 1b Re-Export: site_context wohnt jetzt in
process_engine.process_engine.integrations.temporal.site_context.

Dieses Modul existiert nur damit bestehende Imports
`from hausverwaltung.hausverwaltung.integrations.temporal.site_context import ...`
weiter laufen. Neuer Code sollte direkt aus process_engine importieren.
"""
from process_engine.process_engine.integrations.temporal.site_context import *  # noqa: F401,F403
