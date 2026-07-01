"""Legacy no-op.

Bankverbindung bleibt als normaler Baustein im Datenmodell. Der frühere
Footer-Marker wird durch ``restore_bankverbindung_body_from_footer_marker``
wieder entfernt.
"""

from __future__ import annotations

def execute() -> None:
	return
