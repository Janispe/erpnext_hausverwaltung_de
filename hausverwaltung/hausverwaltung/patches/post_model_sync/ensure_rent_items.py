def execute() -> None:
	try:
		from hausverwaltung.hausverwaltung.utils.rent_items import ensure_rent_items
	except Exception:
		return

	try:
		ensure_rent_items()
	except Exception:
		# Settings might not be configured during migrations.
		return
