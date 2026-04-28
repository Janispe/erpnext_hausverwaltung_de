from hausverwaltung.hausverwaltung.patches.post_model_sync.create_hausverwalter_role import (
	execute as sync_roles_and_permissions,
)


def execute():
	"""Re-apply Hausverwalter permissions while respecting DocType capabilities."""
	# Keep behavior "like before": ensure roles exist and (re)sync DocPerms.
	sync_roles_and_permissions()
