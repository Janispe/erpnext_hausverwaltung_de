from __future__ import annotations

from datetime import datetime

import frappe
from frappe.utils import add_days, cint, now_datetime

from hausverwaltung.hausverwaltung.services import mistral_client

DEFAULT_REMOTE_RETENTION_DAYS = 30
REMOTE_DELETE_BATCH_SIZE = 500
MISTRAL_ENGINES = ("mistral_agents", "mistral_basic")


def _retention_days() -> int:
	settings = frappe.get_single("Hausverwaltung Einstellungen")
	days = cint(getattr(settings, "mistral_conversation_retention_days", None))
	return days if 1 <= days <= 3650 else DEFAULT_REMOTE_RETENTION_DAYS


def delete_expired_mistral_conversations(now: datetime | None = None) -> dict[str, int]:
	"""Delete stale remote Conversations while retaining every local chat message."""
	cutoff = add_days(now or now_datetime(), -_retention_days())
	rows = frappe.get_all(
		"Hausverwaltung Assistant Conversation",
		filters=[
			["engine", "in", list(MISTRAL_ENGINES)],
			["remote_conversation_id", "!=", ""],
			["last_message_on", "<=", cutoff],
		],
		fields=["name", "remote_conversation_id", "last_message_on"],
		order_by="last_message_on asc",
		limit=REMOTE_DELETE_BATCH_SIZE,
	)

	deleted = 0
	failed = 0
	for row in rows:
		name = str(row.get("name") or "").strip()
		remote_id = str(row.get("remote_conversation_id") or "").strip()
		if not name or not remote_id:
			continue
		try:
			mistral_client.delete_agent_conversation(remote_id)
		except mistral_client.MistralError as exc:
			failed += 1
			frappe.log_error(
				title="Mistral-Conversation konnte nicht gelöscht werden",
				message=f"Lokale Conversation {name}: {exc}",
			)
			continue

		# Clear only the same stale remote ID. This prevents a concurrently renewed
		# local conversation from losing its new Mistral reference.
		current = frappe.db.get_value(
			"Hausverwaltung Assistant Conversation",
			name,
			["remote_conversation_id", "last_message_on"],
			as_dict=True,
		)
		if not current or str(current.get("remote_conversation_id") or "").strip() != remote_id:
			continue
		if current.get("last_message_on") and current.get("last_message_on") > cutoff:
			continue
		frappe.db.set_value(
			"Hausverwaltung Assistant Conversation",
			name,
			{
				"remote_conversation_id": "",
				"remote_conversation_deleted_on": now or now_datetime(),
			},
			update_modified=False,
		)
		deleted += 1

	return {"found": len(rows), "deleted": deleted, "failed": failed}
