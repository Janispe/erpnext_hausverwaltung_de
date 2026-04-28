from __future__ import annotations

from hausverwaltung.hausverwaltung.integrations.temporal.config import get_temporal_settings

try:
	from temporalio.client import Client
except Exception:  # pragma: no cover - runtime dependency guard
	Client = None  # type: ignore[assignment]


async def get_temporal_client() -> Client:
	if Client is None:
		raise RuntimeError("temporalio package is not installed")

	settings = get_temporal_settings()
	return await Client.connect(settings.address, namespace=settings.namespace)
