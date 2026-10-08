"""Site-free regression tests for contract-bound, unsent mail drafts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from unittest import TestCase

from .email_draft_contract import (
	DraftCreationRejected,
	EmailDraftError,
	addresses,
	classify_remote,
	configured_addresses,
	create_remote_draft,
	fingerprint,
	message_ids,
	prepare_payload,
	request_key,
)

HEADER = "header:X-Hausverwaltung-Draft-ID:asText"
SENDER = "verwaltung@example.test"
TENANT = "mieter@example.test"
PARTNER = "partner@example.test"


@dataclass(frozen=True)
class Mailbox:
	"""The relevant fields of the provider's ArchiveMailbox contract."""

	id: str
	role: str | None


@dataclass(frozen=True)
class Message:
	"""The same reply and mailbox fields supplied by ArchiveMessage."""

	id: str = "source-1"
	thread_id: str = "thread-1"
	mailbox_ids: tuple[str, ...] = ("inbox",)
	keywords: tuple[str, ...] = ()
	rfc_message_ids: tuple[str, ...] = ("original@example.test",)
	in_reply_to: tuple[str, ...] = ()
	references: tuple[str, ...] = ()
	sender: tuple[dict[str, str], ...] = field(default_factory=lambda: ({"email": TENANT},))
	raw: dict = field(default_factory=dict)


def payload(**changes):
	arguments = {
		"identity": {"mietvertrag": "MV-1", "customer": "C-1", "wohnung": "W-1"},
		"archive_account": "AA-1",
		"own_addresses": [SENDER],
		"partner_addresses": [TENANT, PARTNER],
		"default_recipients": [TENANT],
		"subject": "Re: Reparatur",
		"message": "Guten Tag,\nwir haben Ihren Hinweis erhalten.\n",
	}
	arguments.update(changes)
	return prepare_payload(**arguments)


class ProviderFixture:
	"""Persist remote messages independently of the caller's success or failure."""

	def __init__(self, backend):
		self.backend = backend
		self.mailboxes = [Mailbox("drafts", "drafts"), Mailbox("sent", "sent"), Mailbox("inbox", "inbox")]
		self.messages = []
		self.create_calls = []
		self.query_calls = []
		self.timeout_after_create = False
		self.hide_messages = False
		self.failure_before_create = None

	def assert_locked(self):
		if not self.backend.lock_active:
			raise AssertionError("Provider operations must share the request lock.")

	def find_draft_messages(self, draft_token):
		self.assert_locked()
		self.query_calls.append(draft_token)
		self.backend.events.append("find")
		if self.hide_messages:
			return []
		return [message for message in self.messages if message.raw.get(HEADER) == draft_token]

	def list_mailboxes(self):
		self.assert_locked()
		return self.mailboxes

	def create_draft(self, **arguments):
		self.assert_locked()
		if not self.backend.records[self.backend.active_key].get("creation_started"):
			raise AssertionError("Creation intent must be persisted before the side effect.")
		self.create_calls.append(arguments)
		self.backend.events.append("create")
		if self.failure_before_create is not None:
			raise self.failure_before_create
		message_id = f"remote-{len(self.create_calls)}"
		self.messages.append(
			Message(
				id=message_id,
				mailbox_ids=(arguments["mailbox_id"],),
				keywords=("$draft",),
				rfc_message_ids=(arguments["rfc_message_id"],),
				in_reply_to=arguments["in_reply_to"],
				references=arguments["references"],
				sender=({"email": arguments["sender"]},),
				raw={HEADER: arguments["draft_token"]},
			)
		)
		if self.timeout_after_create:
			raise TimeoutError("The server accepted the draft before the connection timed out.")
		return message_id


class BackendFixture:
	"""Durable request reservations with an observable per-request lock."""

	site = "erp.example.test"
	user = "openclaw@example.test"

	def __init__(self):
		self.records = {}
		self.events = []
		self.lock_keys = []
		self.lock_active = False
		self.active_key = None
		self.creation_claimed_elsewhere = False
		self.creation_attempts = 0
		self.claims = {}
		self.preflight_failure = None
		self.release_failure = None
		self.provider = ProviderFixture(self)

	@contextmanager
	def lock(self, key):
		if self.lock_active:
			raise AssertionError("Unexpected nested lock.")
		self.lock_active = True
		self.active_key = key
		self.lock_keys.append(key)
		self.events.append("lock")
		try:
			yield
		finally:
			self.events.append("unlock")
			self.lock_active = False
			self.active_key = None

	def assert_locked(self):
		if not self.lock_active:
			raise AssertionError("Reservations and result updates must share the request lock.")

	def reserve(self, key, digest, prepared):
		self.assert_locked()
		self.events.append("reserve")
		if key in self.records:
			return self.records[key], True
		record = {
			"fingerprint": digest,
			"draft_token": f"hv-{key}",
			"rfc_message_id": f"hv-{key}@erp.example.test",
			"payload": prepared,
			"creation_started": False,
		}
		self.records[key] = record
		return record, False

	def mark_creation_started(self, record):
		self.assert_locked()
		self.events.append("mark_creation_started")
		if self.creation_claimed_elsewhere:
			raise EmailDraftError("REMOTE_STATE_UNCERTAIN", "A concurrent worker already claimed creation.")
		record["creation_started"] = True
		self.creation_attempts += 1
		record["creation_attempt"] = f"attempt-{self.creation_attempts}"
		self.claims[self.active_key] = record["creation_attempt"]

	def create_draft(self, **arguments):
		self.assert_locked()
		if self.preflight_failure is not None:
			self.events.append("preflight_rejected")
			raise self.preflight_failure
		return self.provider.create_draft(**arguments)

	def release_creation_claim(self, record):
		self.assert_locked()
		self.events.append("release_creation_claim")
		if self.release_failure is not None:
			raise self.release_failure
		if self.claims.get(self.active_key) != record.get("creation_attempt"):
			raise EmailDraftError("REMOTE_STATE_UNCERTAIN", "Creation claim belongs to another worker.")
		self.claims.pop(self.active_key)
		record["creation_started"] = False
		record["creation_attempt"] = None

	def record_created(self, record, message_id):
		self.assert_locked()
		self.events.append("record_created")
		record.update(provider_message_id=message_id, status="Draft")

	def record_remote(self, record, state, remote):
		self.assert_locked()
		self.events.append("record_remote")
		record.update(provider_message_id=remote.id, status=state)

	def result(self, record, state, remote, reused):
		self.assert_locked()
		self.events.append("result")
		return {
			"status": state,
			"provider_message_id": remote.id if remote else record.get("provider_message_id"),
			"reused": reused,
		}


class DraftAssertions(TestCase):
	def assert_error(self, code, operation, *args, **kwargs):
		with self.assertRaises(EmailDraftError) as raised:
			operation(*args, **kwargs)
		self.assertEqual(raised.exception.code, code)


class TestDraftPayload(DraftAssertions):
	def test_reply_to_is_used_and_reply_headers_preserve_the_conversation(self):
		source = Message(
			rfc_message_ids=("<original@example.test>",),
			references=("<older@example.test>", "original@example.test", "older@example.test"),
			raw={"replyTo": [{"email": PARTNER}]},
		)
		prepared = payload(reply=source, reply_to_message="ARCHIVE-1")
		self.assertEqual(prepared["recipients"], [PARTNER])
		self.assertEqual(prepared["in_reply_to"], ["original@example.test"])
		self.assertEqual(prepared["references"], ["older@example.test", "original@example.test"])
		self.assertEqual(prepared["reply_to_message"], "ARCHIVE-1")

	def test_sender_is_fallback_when_source_has_no_reply_to(self):
		prepared = payload(reply=Message(sender=({"email": PARTNER},)))
		self.assertEqual(prepared["recipients"], [PARTNER])

	def test_in_reply_to_is_preserved_when_source_has_no_references(self):
		prepared = payload(reply=Message(in_reply_to=("<older@example.test>",)))
		self.assertEqual(prepared["references"], ["older@example.test", "original@example.test"])

	def test_new_draft_has_no_reply_headers(self):
		prepared = payload()
		self.assertEqual(prepared["in_reply_to"], [])
		self.assertEqual(prepared["references"], [])
		self.assertEqual(prepared["reply_to_message"], "")

	def test_missing_source_message_id_fails_closed(self):
		self.assert_error("MISSING_REPLY_ID", payload, reply=Message(rfc_message_ids=()))

	def test_reply_to_must_belong_to_this_contract(self):
		self.assert_error(
			"RECIPIENT_MISMATCH",
			payload,
			reply=Message(raw={"replyTo": [{"email": "other-contract@example.test"}]}),
		)

	def test_explicit_recipients_can_override_reply_to_with_known_contract_partner(self):
		prepared = payload(reply=Message(raw={"replyTo": [{"email": PARTNER}]}), recipients=[TENANT])
		self.assertEqual(prepared["recipients"], [TENANT])

	def test_both_to_and_cc_reject_other_contracts(self):
		for changes in (
			{"recipients": ["other-contract@example.test"]},
			{"cc": ["other-contract@example.test"]},
		):
			with self.subTest(changes=changes):
				self.assert_error("RECIPIENT_MISMATCH", payload, **changes)

	def test_own_address_is_allowed_only_as_copy(self):
		self.assertEqual(payload(cc=[SENDER])["cc"], [SENDER])
		self.assert_error("RECIPIENT_MISMATCH", payload, recipients=[SENDER])

	def test_normalization_removes_duplicates_between_to_and_cc(self):
		prepared = payload(recipients=[TENANT.upper(), TENANT], cc=[TENANT, PARTNER.upper(), PARTNER])
		self.assertEqual(prepared["recipients"], [TENANT])
		self.assertEqual(prepared["cc"], [PARTNER])

	def test_multiple_configured_senders_require_explicit_selection(self):
		own = [SENDER, "office@example.test"]
		self.assert_error("AMBIGUOUS_SENDER", payload, own_addresses=own)
		self.assertEqual(payload(own_addresses=own, sender=own[1])["sender"], own[1])

	def test_unconfigured_sender_is_rejected(self):
		self.assert_error("INVALID_SENDER", payload, sender="other-mailbox@example.test")

	def test_subject_and_addresses_reject_header_injection(self):
		for subject in ("Hello\r\nBcc: attacker@example.test", "Hello\nBcc: attacker@example.test"):
			with self.subTest(subject=subject):
				self.assert_error("INVALID_ARGUMENT", payload, subject=subject)
		for changes in (
			{"recipients": [TENANT + "\r\nBcc: attacker@example.test"]},
			{"cc": [PARTNER + "\nBcc: attacker@example.test"]},
			{"sender": SENDER + "\r\nBcc: attacker@example.test"},
		):
			with self.subTest(changes=changes):
				self.assert_error("INVALID_ARGUMENT", payload, **changes)

	def test_reply_headers_reject_whitespace_and_embedded_brackets(self):
		for value in (
			"original@example.test\r\nBcc: attacker@example.test",
			"invalid message@example.test",
			"a<b@example.test",
		):
			with self.subTest(value=value):
				self.assert_error("INVALID_REPLY_HEADERS", payload, reply=Message(rfc_message_ids=(value,)))

	def test_reply_headers_require_a_list_or_tuple_of_strings(self):
		for values in (None, "original@example.test", 123, {"id": "original@example.test"}, (None,), (123,)):
			with self.subTest(values=values):
				self.assert_error("INVALID_REPLY_HEADERS", message_ids, values)

	def test_reply_headers_reject_malformed_wrappers_and_control_characters(self):
		for value in (
			"<<original@example.test>>",
			"<original@example.test",
			"original@example.test>",
			"<>",
			"original\x00@example.test",
			"original\x01@example.test",
		):
			with self.subTest(value=value):
				self.assert_error("INVALID_REPLY_HEADERS", message_ids, (value,))

	def test_reply_headers_enforce_count_and_individual_length_bounds(self):
		self.assertEqual(len(message_ids(tuple(f"id-{index}@example.test" for index in range(100)))), 100)
		self.assert_error(
			"INVALID_REPLY_HEADERS", message_ids, tuple(f"id-{index}@example.test" for index in range(101))
		)
		self.assertEqual(message_ids(("x" * 998,)), ["x" * 998])
		self.assert_error("INVALID_REPLY_HEADERS", message_ids, ("x" * 999,))

	def test_bounded_wrapped_reply_header_is_normalized_once(self):
		self.assertEqual(message_ids((" <original@example.test> ",)), ["original@example.test"])
		self.assertEqual(message_ids(()), [])
		self.assertEqual(message_ids([]), [])

	def test_subject_length_and_nonempty_content_limits(self):
		self.assertEqual(len(payload(subject="x" * 500)["subject"]), 500)
		for changes in (
			{"subject": "x" * 501},
			{"subject": " "},
			{"subject": None},
			{"message": "\n "},
			{"message": None},
		):
			with self.subTest(changes=changes):
				self.assert_error("INVALID_ARGUMENT", payload, **changes)

	def test_body_character_and_utf8_byte_limits(self):
		self.assertEqual(len(payload(message="x" * 20_000)["message"]), 20_000)
		self.assertEqual(len(payload(message="😀" * 12_500)["message"].encode()), 50_000)
		for message in ("x" * 20_001, "😀" * 12_501):
			with self.subTest(size=len(message)):
				self.assert_error("INVALID_ARGUMENT", payload, message=message)

	def test_body_rejects_unencodable_unicode_and_nul(self):
		for message in ("Antwort\ud800", "Antwort\udfff", "Antwort\x00mit NUL"):
			with self.subTest(message=repr(message)):
				self.assert_error("INVALID_ARGUMENT", payload, message=message)

	def test_recipients_are_bounded_across_to_and_cc(self):
		partners = [f"p{index}@example.test" for index in range(21)]
		self.assertEqual(
			len(payload(partner_addresses=partners[:20], recipients=partners[:10], cc=partners[10:20])["cc"]),
			10,
		)
		self.assert_error(
			"INVALID_ARGUMENT",
			payload,
			partner_addresses=partners[:20],
			recipients=partners[:10],
			cc=[*partners[10:20], SENDER],
		)

	def test_missing_and_nonlist_recipients_are_rejected(self):
		self.assert_error("MISSING_RECIPIENT", payload, recipients=[])
		for value in (TENANT, {"email": TENANT}, [None], [TENANT] * 21):
			with self.subTest(value=value):
				self.assert_error("INVALID_ARGUMENT", payload, recipients=value)

	def test_configured_addresses_allow_common_configuration_separators(self):
		self.assertEqual(
			configured_addresses(f" {SENDER}; {PARTNER}\n{TENANT}, {TENANT.upper()}"),
			[SENDER, PARTNER, TENANT],
		)
		self.assertEqual(addresses(None), [])
		self.assertEqual(message_ids(("<a@example.test>", "a@example.test")), ["a@example.test"])


class TestDraftRequestIdentity(DraftAssertions):
	def test_fingerprint_changes_when_contract_or_content_changes(self):
		prepared = payload()
		self.assertEqual(fingerprint(prepared), fingerprint(dict(reversed(list(prepared.items())))))
		self.assertNotEqual(fingerprint(prepared), fingerprint(payload(message="Anderer Inhalt")))
		self.assertNotEqual(
			fingerprint(prepared),
			fingerprint(payload(identity={"mietvertrag": "MV-2", "customer": "C-2", "wohnung": "W-2"})),
		)

	def test_request_key_is_scoped_to_site_user_and_normalized_request_id(self):
		key = request_key("site-1", "user-1", "request-1")
		self.assertEqual(key, request_key("site-1", "user-1", " request-1 "))
		self.assertNotEqual(key, request_key("site-2", "user-1", "request-1"))
		self.assertNotEqual(key, request_key("site-1", "user-2", "request-1"))
		self.assertNotEqual(key, request_key("site-1", "user-1", "request-2"))

	def test_request_id_is_required_and_bounded(self):
		self.assertEqual(len(request_key("site", "user", "r" * 128)), 64)
		for value in (None, "", " ", "r" * 129):
			with self.subTest(value=value):
				self.assert_error("INVALID_ARGUMENT", request_key, "site", "user", value)


class TestRemoteDraftLifecycle(DraftAssertions):
	def setUp(self):
		self.backend = BackendFixture()
		self.prepared = payload()

	def create(self, request_id="request-1", prepared=None):
		return create_remote_draft(self.backend, self.prepared if prepared is None else prepared, request_id)

	def classify(self, messages):
		return classify_remote(
			messages, draft_token="token-1", sender=SENDER, mailboxes=self.backend.provider.mailboxes
		)

	def remote(self, **changes):
		return replace(
			Message(
				id="remote-1",
				mailbox_ids=("drafts",),
				keywords=("$draft",),
				sender=({"email": SENDER},),
				raw={HEADER: "token-1"},
			),
			**changes,
		)

	def test_creation_reserves_and_marks_intent_under_lock_before_remote_side_effect(self):
		result = self.create()
		self.assertEqual(result, {"status": "Draft", "provider_message_id": "remote-1", "reused": False})
		self.assertEqual(
			self.backend.events,
			[
				"lock",
				"reserve",
				"find",
				"mark_creation_started",
				"create",
				"record_created",
				"result",
				"unlock",
			],
		)
		self.assertEqual(
			self.backend.lock_keys, [request_key(self.backend.site, self.backend.user, "request-1")]
		)
		self.assertFalse(self.backend.lock_active)

	def test_concurrent_database_claim_stops_create_despite_stale_reservation(self):
		self.backend.creation_claimed_elsewhere = True
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(self.backend.events, ["lock", "reserve", "find", "mark_creation_started", "unlock"])
		self.assertEqual(self.backend.provider.create_calls, [])
		self.assertEqual(self.backend.provider.messages, [])
		self.assertFalse(self.backend.lock_active)

	def test_provider_receives_reply_headers_recipients_and_plaintext_without_submission(self):
		prepared = payload(reply=Message(references=("older@example.test",)), cc=[PARTNER])
		self.create(prepared=prepared)
		arguments = self.backend.provider.create_calls[0]
		self.assertEqual(arguments["in_reply_to"], ("original@example.test",))
		self.assertEqual(arguments["references"], ("older@example.test", "original@example.test"))
		self.assertEqual(arguments["recipients"], [TENANT])
		self.assertEqual(arguments["cc"], [PARTNER])
		self.assertEqual(arguments["text_body"], prepared["message"])
		self.assertEqual(arguments["mailbox_id"], "drafts")
		self.assertEqual(
			set(arguments),
			{
				"mailbox_id",
				"sender",
				"recipients",
				"cc",
				"subject",
				"text_body",
				"draft_token",
				"rfc_message_id",
				"in_reply_to",
				"references",
			},
		)

	def test_repeat_same_request_recovers_existing_draft_without_second_create(self):
		first = self.create()
		second = self.create()
		self.assertEqual(first["provider_message_id"], second["provider_message_id"])
		self.assertTrue(second["reused"])
		self.assertEqual(len(self.backend.provider.create_calls), 1)
		self.assertEqual(len(self.backend.records), 1)

	def test_reused_request_with_different_content_is_rejected_before_remote_query(self):
		self.create()
		queries = len(self.backend.provider.query_calls)
		self.assert_error("REQUEST_CONFLICT", self.create, prepared=payload(message="Anderer Inhalt"))
		self.assertEqual(len(self.backend.provider.query_calls), queries)
		self.assertEqual(len(self.backend.provider.create_calls), 1)
		self.assertFalse(self.backend.lock_active)

	def test_timeout_after_server_side_effect_recovers_existing_marker(self):
		self.backend.provider.timeout_after_create = True
		with self.assertRaises(TimeoutError):
			self.create()
		self.assertEqual(len(self.backend.provider.messages), 1)
		self.assertNotIn("provider_message_id", next(iter(self.backend.records.values())))
		self.assertTrue(next(iter(self.backend.records.values()))["creation_started"])
		self.assertEqual(len(self.backend.claims), 1)
		self.assertNotIn("release_creation_claim", self.backend.events)
		self.assertFalse(self.backend.lock_active)
		result = self.create()
		self.assertEqual(result["status"], "Draft")
		self.assertTrue(result["reused"])
		self.assertEqual(result["provider_message_id"], "remote-1")
		self.assertEqual(len(self.backend.provider.create_calls), 1)

	def test_uncertain_timeout_does_not_duplicate_when_remote_query_is_temporarily_empty(self):
		self.backend.provider.timeout_after_create = True
		with self.assertRaises(TimeoutError):
			self.create()
		self.backend.provider.hide_messages = True
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(len(self.backend.provider.create_calls), 1)
		self.backend.provider.hide_messages = False
		self.assertEqual(self.create()["provider_message_id"], "remote-1")

	def test_missing_previously_created_draft_is_uncertain_and_never_recreated(self):
		self.create()
		self.backend.provider.messages.clear()
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(len(self.backend.provider.create_calls), 1)
		self.assertEqual(next(iter(self.backend.records.values()))["status"], "Draft")

	def test_unknown_provider_failure_without_remote_match_is_not_blindly_repeated(self):
		self.backend.provider.failure_before_create = RuntimeError("Unknown server outcome")
		with self.assertRaisesRegex(RuntimeError, "Unknown server outcome"):
			self.create()
		self.assertEqual(self.backend.provider.messages, [])
		self.assertTrue(next(iter(self.backend.records.values()))["creation_started"])
		self.assertNotIn("release_creation_claim", self.backend.events)
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(len(self.backend.provider.create_calls), 1)

	def test_proven_preflight_rights_rejection_releases_claim_and_allows_same_request_retry(self):
		self.backend.preflight_failure = DraftCreationRejected("Mailbox rights do not permit drafts.")
		self.assert_error("DRAFT_NOT_CREATED", self.create)
		record = next(iter(self.backend.records.values()))
		self.assertFalse(record["creation_started"])
		self.assertIsNone(record["creation_attempt"])
		self.assertEqual(self.backend.claims, {})
		self.assertEqual(self.backend.provider.create_calls, [])
		self.assertEqual(self.backend.provider.messages, [])
		token = record["draft_token"]
		self.backend.preflight_failure = None
		result = self.create()
		self.assertEqual(result["status"], "Draft")
		self.assertTrue(result["reused"])
		self.assertEqual(self.backend.provider.create_calls[0]["draft_token"], token)
		self.assertEqual(len(self.backend.provider.messages), 1)
		self.assertEqual(self.backend.creation_attempts, 2)

	def test_explicit_server_rejection_can_retry_same_request_without_duplicate_draft(self):
		self.backend.provider.failure_before_create = DraftCreationRejected(
			"The server explicitly rejected creation."
		)
		self.assert_error("DRAFT_NOT_CREATED", self.create)
		self.assertEqual(self.backend.provider.messages, [])
		record = next(iter(self.backend.records.values()))
		self.assertFalse(record["creation_started"])
		self.assertEqual(self.backend.claims, {})
		first_arguments = self.backend.provider.create_calls[0]
		self.backend.provider.failure_before_create = None
		self.assertEqual(self.create()["status"], "Draft")
		self.assertEqual(len(self.backend.provider.create_calls), 2)
		self.assertEqual(self.backend.provider.create_calls[1], first_arguments)
		self.assertEqual(len(self.backend.provider.messages), 1)

	def test_same_error_code_without_proven_rejection_type_keeps_creation_claim(self):
		self.backend.provider.failure_before_create = EmailDraftError(
			"DRAFT_NOT_CREATED", "Unproven rejection"
		)
		self.assert_error("DRAFT_NOT_CREATED", self.create)
		self.assertTrue(next(iter(self.backend.records.values()))["creation_started"])
		self.assertNotIn("release_creation_claim", self.backend.events)
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(len(self.backend.provider.create_calls), 1)

	def test_failed_claim_release_never_opens_another_create_attempt(self):
		self.backend.provider.failure_before_create = DraftCreationRejected(
			"The server explicitly rejected creation."
		)
		self.backend.release_failure = RuntimeError("Database release failed")
		with self.assertRaisesRegex(RuntimeError, "Database release failed"):
			self.create()
		self.assertTrue(next(iter(self.backend.records.values()))["creation_started"])
		self.assertEqual(len(self.backend.claims), 1)
		self.assertFalse(self.backend.lock_active)
		self.backend.release_failure = None
		self.backend.provider.failure_before_create = None
		self.assert_error("REMOTE_STATE_UNCERTAIN", self.create)
		self.assertEqual(len(self.backend.provider.create_calls), 1)
		self.assertEqual(self.backend.provider.messages, [])

	def test_proven_rejection_does_not_allow_request_content_to_change(self):
		self.backend.preflight_failure = DraftCreationRejected("Mailbox rights do not permit drafts.")
		self.assert_error("DRAFT_NOT_CREATED", self.create)
		self.backend.preflight_failure = None
		queries = len(self.backend.provider.query_calls)
		self.assert_error("REQUEST_CONFLICT", self.create, prepared=payload(message="Anderer Inhalt"))
		self.assertEqual(len(self.backend.provider.query_calls), queries)
		self.assertEqual(self.backend.provider.create_calls, [])
		self.assertEqual(self.create()["status"], "Draft")

	def test_missing_or_multiple_draft_folders_fail_before_creation_starts(self):
		for mailboxes in (
			[Mailbox("sent", "sent")],
			[Mailbox("drafts-1", "drafts"), Mailbox("drafts-2", "drafts")],
		):
			with self.subTest(mailboxes=mailboxes):
				backend = BackendFixture()
				backend.provider.mailboxes = mailboxes
				self.assert_error(
					"DRAFT_MAILBOX_CONFLICT", create_remote_draft, backend, self.prepared, "request-1"
				)
				self.assertEqual(backend.provider.create_calls, [])
				self.assertFalse(next(iter(backend.records.values()))["creation_started"])

	def test_retry_before_creation_starts_can_succeed_after_folder_fix(self):
		mailboxes = self.backend.provider.mailboxes
		self.backend.provider.mailboxes = []
		self.assert_error("DRAFT_MAILBOX_CONFLICT", self.create)
		self.backend.provider.mailboxes = mailboxes
		self.assertEqual(self.create()["status"], "Draft")
		self.assertEqual(len(self.backend.provider.create_calls), 1)

	def test_sent_copy_updates_status_using_actual_remote_message(self):
		self.create()
		self.backend.provider.messages[0] = replace(
			self.backend.provider.messages[0], id="sent-1", mailbox_ids=("sent",), keywords=()
		)
		result = self.create()
		self.assertEqual(result["status"], "Sent")
		self.assertEqual(result["provider_message_id"], "sent-1")
		self.assertEqual(next(iter(self.backend.records.values()))["status"], "Sent")
		self.assertEqual(len(self.backend.provider.create_calls), 1)

	def test_sent_copy_takes_precedence_over_remaining_single_draft_copy(self):
		draft = self.remote()
		sent = replace(draft, id="sent-1", mailbox_ids=("sent",), keywords=())
		self.assertEqual(self.classify([draft, sent]), ("Sent", sent))

	def test_absence_or_keyword_removal_without_sent_folder_does_not_prove_sent(self):
		self.assertEqual(self.classify([]), ("Missing", None))
		for message in (
			self.remote(keywords=()),
			self.remote(mailbox_ids=("inbox",), keywords=()),
			self.remote(mailbox_ids=("unknown-folder",), keywords=()),
			self.remote(mailbox_ids=("sent",), keywords=("$draft",)),
		):
			with self.subTest(message=message):
				self.assert_error("REMOTE_CONFLICT", self.classify, [message])

	def test_missing_or_conflicting_marker_and_changed_sender_are_rejected(self):
		for message in (
			self.remote(raw={}),
			self.remote(raw={HEADER: "token-1-extra"}),
			self.remote(sender=({"email": "other-mailbox@example.test"},)),
			self.remote(sender=()),
			self.remote(sender=({"email": SENDER}, {"email": "other-mailbox@example.test"})),
		):
			with self.subTest(message=message):
				self.assert_error("REMOTE_CONFLICT", self.classify, [message])

	def test_sender_case_changes_do_not_conflict(self):
		message = self.remote(sender=({"email": SENDER.upper()},))
		self.assertEqual(self.classify([message]), ("Draft", message))

	def test_duplicate_draft_or_sent_markers_are_ambiguous(self):
		draft = self.remote()
		sent = replace(draft, mailbox_ids=("sent",), keywords=())
		for messages in ([draft, replace(draft, id="draft-2")], [sent, replace(sent, id="sent-2")]):
			with self.subTest(messages=messages):
				self.assert_error("REMOTE_CONFLICT", self.classify, messages)

	def test_different_request_id_creates_an_independent_draft(self):
		self.create("request-1")
		self.create("request-2")
		self.assertEqual(len(self.backend.provider.create_calls), 2)
		self.assertEqual(len(self.backend.records), 2)
		self.assertNotEqual(
			self.backend.provider.create_calls[0]["draft_token"],
			self.backend.provider.create_calls[1]["draft_token"],
		)


class TestAttachedDraftLifecycle(TestCase):
	def test_same_attachments_retry_once_changed_bytes_conflict(self):
		from .email_attachments import attachment_manifest

		backend = BackendFixture()
		files = [{"filename": "a.pdf", "content_type": "application/pdf", "content": b"%PDF-one"}]
		prepared = payload() | {"attachments": attachment_manifest(files)}
		create_remote_draft(backend, prepared, "request-attachments", attachments=files)
		create_remote_draft(backend, prepared, "request-attachments", attachments=files)
		self.assertEqual(len(backend.provider.create_calls), 1)
		self.assertEqual(backend.provider.create_calls[0]["attachments"], files)
		changed = [files[0] | {"content": b"%PDF-two"}]
		with self.assertRaises(EmailDraftError) as raised:
			create_remote_draft(
				backend,
				payload() | {"attachments": attachment_manifest(changed)},
				"request-attachments",
				attachments=changed,
			)
		self.assertEqual(raised.exception.code, "REQUEST_CONFLICT")
		self.assertEqual(len(backend.provider.create_calls), 1)

	def test_upload_failure_releases_claim_and_retries_same_attachment_request(self):
		from .email_attachments import attachment_manifest

		backend = BackendFixture()
		files = [{"filename": "a.pdf", "content_type": "application/pdf", "content": b"pdf"}]
		prepared = payload() | {"attachments": attachment_manifest(files)}
		backend.provider.failure_before_create = DraftCreationRejected("upload failed before Email/set")
		with self.assertRaises(DraftCreationRejected):
			create_remote_draft(backend, prepared, "request-attachments", attachments=files)
		self.assertFalse(next(iter(backend.records.values()))["creation_started"])
		backend.provider.failure_before_create = None
		create_remote_draft(backend, prepared, "request-attachments", attachments=files)
		self.assertEqual(len(backend.provider.messages), 1)

	def test_manifest_without_matching_bytes_rejects_before_reservation(self):
		backend = BackendFixture()
		with self.assertRaises(EmailDraftError):
			create_remote_draft(
				backend, payload() | {"attachments": [{"sha256": "invented"}]}, "request-attachments"
			)
		self.assertFalse(backend.records)
