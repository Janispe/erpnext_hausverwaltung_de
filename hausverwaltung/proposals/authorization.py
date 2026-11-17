"""Synthetic grants only, never an authentication/Frappe permission substitute.

A future host adapter must derive identities from the authenticated session and
perform current object, field and domain checks. Do not expose Identity to RPC.
"""
from dataclasses import dataclass


class Denied(PermissionError):
	pass


@dataclass(frozen=True)
class Identity:
	"""Trusted host identity, never deserialize this from agent/client input."""

	name: str
	human: bool = False


class SyntheticAuthorization:
	def __init__(self, store):
		self.store = store

	def require(self, actor, target, capability):
		if not isinstance(actor, Identity) or not actor.name:
			raise Denied("Authenticated host identity required")
		if not self.store.db.execute("SELECT 1 FROM grant_rule WHERE actor=? AND target=? AND capability=?",
							   (actor.name, target, capability)).fetchone():
			raise Denied("Operation unavailable")
