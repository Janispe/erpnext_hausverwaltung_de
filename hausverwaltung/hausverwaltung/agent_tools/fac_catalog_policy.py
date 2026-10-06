"""Server-owned routing policy transported in MCP Tool._meta (no Frappe)."""

ROUTING_META_KEY = "hausverwaltung/routing"
ROUTING_VERSION = 1


def routing_metadata(audience, model_max_chars=10_000):
	if audience not in {"model", "code"}:
		raise ValueError("Tool audience must be model or code")
	if (
		isinstance(model_max_chars, bool)
		or not isinstance(model_max_chars, int)
		or not 1 <= model_max_chars <= 40_000
	):
		raise ValueError("Invalid model output budget")
	return {
		ROUTING_META_KEY: {
			"version": ROUTING_VERSION,
			"audiences": ["model", "code"] if audience == "model" else ["code"],
			"model_max_chars": model_max_chars if audience == "model" else None,
		}
	}
