"""Phase 8 Stufe 1b Re-Export: client wohnt jetzt in
process_engine.process_engine.integrations.temporal.client.

Dieses Modul existiert nur damit bestehende Imports
`from hausverwaltung.hausverwaltung.integrations.temporal.client import ...`
weiter laufen. Neuer Code sollte direkt aus process_engine importieren.
"""
from process_engine.process_engine.integrations.temporal.client import *  # noqa: F401,F403
