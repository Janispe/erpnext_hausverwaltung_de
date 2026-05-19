"""Phase 8 Stufe 1b Re-Export: config wohnt jetzt in
process_engine.process_engine.integrations.temporal.config.

Dieses Modul existiert nur damit bestehende Imports
`from hausverwaltung.hausverwaltung.integrations.temporal.config import ...`
weiter laufen. Neuer Code sollte direkt aus process_engine importieren.
"""
from process_engine.process_engine.integrations.temporal.config import *  # noqa: F401,F403
