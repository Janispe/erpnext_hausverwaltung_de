from __future__ import annotations


def get_data(data: dict | None = None) -> dict:
	"""Erweitert das Mieter-Dashboard um die Connection zu Mietverträgen."""
	data = dict(data or {})
	data.setdefault("transactions", [])
	data.setdefault("non_standard_fieldnames", {})

	# "Mietvertrag" verlinkt auf Customer über Feld "kunde" (nicht "customer").
	data["non_standard_fieldnames"].setdefault("Mietvertrag", "kunde")

	label = "Hausverwaltung"
	group = None
	for entry in data["transactions"]:
		if isinstance(entry, dict) and entry.get("label") == label:
			group = entry
			break
	if group is None:
		group = {"label": label, "items": []}
		data["transactions"].append(group)

	items = group.setdefault("items", [])
	if "Mietvertrag" not in items:
		items.append("Mietvertrag")

	return data
