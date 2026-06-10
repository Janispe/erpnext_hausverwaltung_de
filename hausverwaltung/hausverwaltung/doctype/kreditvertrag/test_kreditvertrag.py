"""Tests für Kreditvertrag.

Drei Test-Schichten:
1. Pure Unit-Tests (Parser, Math) — laufen ohne Frappe-DB.
2. Mock-basierte Tests für Compute-Methoden (status, restschuld_nach).
3. Integration-Tests (IntegrationTestCase) für JE-Erstellung, PLE-Negativ,
   Rollback bei Reconcile-Fehler und Storno-Hook. Diese brauchen eine
   Site mit Liability- + Expense-Konten und einem Bank Account — werden
   übersprungen wenn die Site-Daten nicht passen.
"""

from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from hausverwaltung.hausverwaltung.doctype.kreditvertrag import kreditvertrag as kv_mod
from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
	RESTSCHULD_EPSILON,
	STATUS_ABGELOEST,
	STATUS_AKTIV,
	_create_journal_entry_for_rate,
	_parse_amount,
	assign_kreditrate,
	link_bank_transaction_to_kreditvertrag_rate,
	on_journal_entry_cancel,
)



def _make_fake_doc(
	anfangs_restschuld: float = 100_000.0,
	rates: list[dict] | None = None,
	darlehenskonto: str = "3301 - Verb Bank - TC",
	company: str = "Test Company",
) -> SimpleNamespace:
	"""Baut ein minimales Doc-Stand-in, das Kreditvertrag._compute_*-Methoden konsumieren können."""
	rates = rates or []
	plan = []
	for idx, r in enumerate(rates, start=1):
		row = SimpleNamespace(
			idx=idx,
			name=r.get("name", f"row_{idx}"),
			faelligkeitsdatum=r["faelligkeitsdatum"],
			zinsanteil=r.get("zinsanteil", 0),
			tilgungsanteil=r.get("tilgungsanteil", 0),
			sondertilgung=r.get("sondertilgung", 0),
			gesamtbetrag=r.get("gesamtbetrag", 0),
			restschuld_nach=r.get("restschuld_nach", 0),
			journal_entry=r.get("journal_entry"),
			bank_transaction=r.get("bank_transaction"),
			gebucht_am=r.get("gebucht_am"),
		)
		# Frappe-Doc-Stand-in: .get() für die Compute-Methoden, die mit der Frappe-API rechnen
		row.get = (lambda r=row: lambda key, default=None: getattr(r, key, default))()
		plan.append(row)
	doc = SimpleNamespace(
		anfangs_restschuld=anfangs_restschuld,
		darlehenskonto=darlehenskonto,
		company=company,
		_plan=plan,
		aktuelle_restschuld=0.0,
		gl_saldo_darlehenskonto=0.0,
		restschuld_abweichung=0.0,
		status=None,
	)

	def _get(name, default=None):
		if name == "plan":
			return doc._plan
		return getattr(doc, name, default)

	doc.get = _get
	return doc


class TestParseAmount(unittest.TestCase):
	def test_german_format(self):
		self.assertEqual(_parse_amount("1.234,56"), 1234.56)

	def test_us_format(self):
		self.assertEqual(_parse_amount("1234.56"), 1234.56)

	def test_us_format_with_thousands(self):
		self.assertEqual(_parse_amount("1,234.56"), 1234.56)

	def test_plain_integer(self):
		self.assertEqual(_parse_amount("500"), 500.0)

	def test_empty_allow_empty(self):
		self.assertIsNone(_parse_amount("", allow_empty=True))
		self.assertIsNone(_parse_amount("   ", allow_empty=True))
		self.assertIsNone(_parse_amount(None, allow_empty=True))

	def test_empty_default_zero(self):
		self.assertEqual(_parse_amount(""), 0.0)
		self.assertEqual(_parse_amount(None), 0.0)

	def test_eur_symbol(self):
		self.assertEqual(_parse_amount("1.234,56 €"), 1234.56)
		self.assertEqual(_parse_amount("123 EUR"), 123.0)

	def test_space_thousands(self):
		self.assertEqual(_parse_amount("6 786,82"), 6786.82)


class TestLoanMatchHints(unittest.TestCase):
	def test_extracts_contract_number_and_split_from_reference(self):
		hints = kv_mod._extract_loan_match_hints(
			"LEISTUNGEN PER 30.04.2026, IBAN DE94100400000863751405, "
			"AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29"
		)

		self.assertEqual(hints["vertragsnummer"], "7626440021")
		self.assertAlmostEqual(hints["tilgungsanteil"], 6786.82)
		self.assertAlmostEqual(hints["zinsanteil"], 3858.29)

	def test_extracts_contract_number_without_comma(self):
		hints = kv_mod._extract_loan_match_hints(
			"Darlehensnr 7626440021 Tilgung 6786,82 Zinsen 3858,29"
		)

		self.assertEqual(hints["vertragsnummer"], "7626440021")
		self.assertAlmostEqual(hints["tilgungsanteil"], 6786.82)
		self.assertAlmostEqual(hints["zinsanteil"], 3858.29)

	def test_candidate_rates_prefers_reference_contract_and_split(self):
		def row(name, zins, tilgung):
			item = SimpleNamespace(
				name=name,
				idx=1,
				faelligkeitsdatum=datetime.date(2026, 4, 30),
				zinsanteil=zins,
				tilgungsanteil=tilgung,
				sondertilgung=0,
				gesamtbetrag=zins + tilgung,
				journal_entry=None,
			)
			item.get = lambda key, default=None: getattr(item, key, default)
			return item

		def kv(name, vertragsnummer, plan_row):
			doc = SimpleNamespace(
				name=name,
				vertragsnummer=vertragsnummer,
				lieferant="Commerzbank",
				match_tolerance_days=7,
				bank_account="BA-8090",
				_plan=[plan_row],
			)
			doc.get = (
				lambda key, default=None: doc._plan
				if key == "plan"
				else getattr(doc, key, default)
			)
			return doc

		docs = {
			"KV-1": kv("KV-1", "7626440021", row("R-1", 3858.29, 6786.82)),
			"KV-2": kv("KV-2", "OTHER", row("R-2", 3000.00, 7645.11)),
		}

		with patch.object(kv_mod.frappe, "get_all", return_value=["KV-1", "KV-2"]), \
			patch.object(kv_mod.frappe, "get_doc", side_effect=lambda _doctype, name: docs[name]):
			candidates = kv_mod._candidate_rates(
				bank_account="BA-8090",
				amount=10645.11,
				posting_date=datetime.date(2026, 4, 30),
				reference_text="AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertEqual(len(candidates), 1)
		self.assertEqual(candidates[0]["kreditvertrag"], "KV-1")
		self.assertTrue(candidates[0]["vertragsnummer_match"])
		self.assertTrue(candidates[0]["split_match"])

	def test_candidate_rates_keeps_amount_date_match_when_az_does_not_match(self):
		def row(name, zins, tilgung):
			item = SimpleNamespace(
				name=name,
				idx=1,
				faelligkeitsdatum=datetime.date(2026, 4, 30),
				zinsanteil=zins,
				tilgungsanteil=tilgung,
				sondertilgung=0,
				gesamtbetrag=zins + tilgung,
				journal_entry=None,
			)
			item.get = lambda key, default=None: getattr(item, key, default)
			return item

		kv = SimpleNamespace(
			name="KV-1",
			vertragsnummer="",
			lieferant="Commerzbank",
			match_tolerance_days=7,
			bank_account="BA-8090",
			_plan=[row("R-1", 3858.29, 6786.82)],
		)
		kv.get = lambda key, default=None: kv._plan if key == "plan" else getattr(kv, key, default)

		with patch.object(kv_mod.frappe, "get_all", return_value=["KV-1"]), \
			patch.object(kv_mod.frappe, "get_doc", return_value=kv):
			candidates = kv_mod._candidate_rates(
				bank_account="BA-8090",
				amount=10645.11,
				posting_date=datetime.date(2026, 4, 30),
				reference_text="AZ 9999999999 Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertEqual(len(candidates), 1)
		self.assertEqual(candidates[0]["kreditvertrag"], "KV-1")
		self.assertFalse(candidates[0]["vertragsnummer_match"])

	def _fake_row(
		self,
		*,
		name="ROW-1",
		faelligkeitsdatum=datetime.date(2026, 4, 30),
		zinsanteil=0,
		tilgungsanteil=0,
		sondertilgung=0,
		journal_entry=None,
	):
		row = SimpleNamespace(
			name=name,
			idx=1,
			faelligkeitsdatum=faelligkeitsdatum,
			zinsanteil=zinsanteil,
			tilgungsanteil=tilgungsanteil,
			sondertilgung=sondertilgung,
			gesamtbetrag=zinsanteil + tilgungsanteil + sondertilgung,
			journal_entry=journal_entry,
		)
		row.get = lambda key, default=None: getattr(row, key, default)
		return row

	def _fake_kv(self, plan=None):
		kv = SimpleNamespace(
			name="KV-1",
			bank_account="BA-8090",
			vertragsnummer="7626440021",
			lieferant="Commerzbank",
			_plan=list(plan or []),
			saved=False,
		)

		def get(key, default=None):
			if key == "plan":
				return kv._plan
			return getattr(kv, key, default)

		def append(key, data):
			self.assertEqual(key, "plan")
			row = self._fake_row(
				name="NEW-ROW",
				faelligkeitsdatum=data["faelligkeitsdatum"],
				zinsanteil=data["zinsanteil"],
				tilgungsanteil=data["tilgungsanteil"],
				sondertilgung=data["sondertilgung"],
			)
			row.idx = len(kv._plan) + 1
			kv._plan.append(row)
			return row

		def save(ignore_permissions=False):
			kv.saved = True
			kv.save_ignore_permissions = ignore_permissions

		kv.get = get
		kv.append = append
		kv.save = save
		return kv

	def test_statement_rate_is_created_when_no_period_row_exists(self):
		kv = self._fake_kv()
		db = SimpleNamespace(savepoint=MagicMock(), rollback=MagicMock())

		with patch.object(kv_mod.frappe, "db", db), \
			patch.object(kv_mod.frappe, "get_all", return_value=["KV-1"]), \
			patch.object(kv_mod.frappe, "get_doc", return_value=kv), \
			patch.object(
				kv_mod,
				"_book_rate_row_and_reconcile",
				return_value={"journal_entry": "JE-1"},
			) as book:
			result = kv_mod._create_or_book_rate_from_statement(
				bank_account="BA-8090",
				posting_date=datetime.date(2026, 4, 30),
				amount=10645.11,
				bank_transaction="BT-1",
				reference_text="AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertTrue(result["created_from_statement"])
		self.assertEqual(result["journal_entry"], "JE-1")
		self.assertTrue(kv.saved)
		self.assertEqual(len(kv._plan), 1)
		self.assertAlmostEqual(kv._plan[0].zinsanteil, 3858.29)
		self.assertAlmostEqual(kv._plan[0].tilgungsanteil, 6786.82)
		book.assert_called_once()

	def test_statement_rate_blocks_when_future_plan_rows_exist(self):
		kv = self._fake_kv(
			[
				self._fake_row(
					faelligkeitsdatum=datetime.date(2026, 5, 31),
					zinsanteil=3000,
					tilgungsanteil=7000,
				)
			]
		)
		db = SimpleNamespace(savepoint=MagicMock(), rollback=MagicMock())

		with patch.object(kv_mod.frappe, "db", db), \
			patch.object(kv_mod.frappe, "get_all", return_value=["KV-1"]), \
			patch.object(kv_mod.frappe, "get_doc", return_value=kv), \
			patch.object(kv_mod, "_book_rate_row_and_reconcile") as book:
			result = kv_mod._create_or_book_rate_from_statement(
				bank_account="BA-8090",
				posting_date=datetime.date(2026, 4, 30),
				amount=10645.11,
				bank_transaction="BT-1",
				reference_text="AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertTrue(result["blocked"])
		self.assertEqual(result["reason"], "future_plan_rows")
		self.assertFalse(kv.saved)
		book.assert_not_called()

	def test_statement_rate_blocks_when_period_row_differs(self):
		kv = self._fake_kv(
			[
				self._fake_row(
					faelligkeitsdatum=datetime.date(2026, 4, 15),
					zinsanteil=3000,
					tilgungsanteil=7000,
				)
			]
		)
		db = SimpleNamespace(savepoint=MagicMock(), rollback=MagicMock())

		with patch.object(kv_mod.frappe, "db", db), \
			patch.object(kv_mod.frappe, "get_all", return_value=["KV-1"]), \
			patch.object(kv_mod.frappe, "get_doc", return_value=kv), \
			patch.object(kv_mod, "_book_rate_row_and_reconcile") as book:
			result = kv_mod._create_or_book_rate_from_statement(
				bank_account="BA-8090",
				posting_date=datetime.date(2026, 4, 30),
				amount=10645.11,
				bank_transaction="BT-1",
				reference_text="AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertTrue(result["blocked"])
		self.assertEqual(result["reason"], "period_rate_mismatch")
		self.assertFalse(kv.saved)
		book.assert_not_called()

	def test_statement_rate_books_existing_exact_period_row(self):
		row = self._fake_row(
			faelligkeitsdatum=datetime.date(2026, 4, 15),
			zinsanteil=3858.29,
			tilgungsanteil=6786.82,
		)
		kv = self._fake_kv([row])

		with patch.object(kv_mod.frappe, "get_all", return_value=["KV-1"]), \
			patch.object(kv_mod.frappe, "get_doc", return_value=kv), \
			patch.object(
				kv_mod,
				"_book_rate_row_and_reconcile",
				return_value={"journal_entry": "JE-1"},
			) as book:
			result = kv_mod._create_or_book_rate_from_statement(
				bank_account="BA-8090",
				posting_date=datetime.date(2026, 4, 30),
				amount=10645.11,
				bank_transaction="BT-1",
				reference_text="AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29",
			)

		self.assertFalse(result["created_from_statement"])
		self.assertEqual(result["row_name"], row.name)
		self.assertFalse(kv.saved)
		book.assert_called_once()


class TestComputeRestschuld(unittest.TestCase):
	def test_restschuld_nach_chain(self):
		"""3 Raten ohne Sondertilgung: Restschuld zieht sich linear runter."""
		doc = _make_fake_doc(
			anfangs_restschuld=10_000.0,
			rates=[
				{"faelligkeitsdatum": datetime.date(2026, 1, 31), "zinsanteil": 50, "tilgungsanteil": 200},
				{"faelligkeitsdatum": datetime.date(2026, 2, 28), "zinsanteil": 48, "tilgungsanteil": 202},
				{"faelligkeitsdatum": datetime.date(2026, 3, 31), "zinsanteil": 46, "tilgungsanteil": 204},
			],
		)
		kv_mod.Kreditvertrag._compute_zeilen_summen(doc)
		kv_mod.Kreditvertrag._compute_restschuld_nach(doc)
		self.assertAlmostEqual(doc._plan[0].restschuld_nach, 9800.0, places=2)
		self.assertAlmostEqual(doc._plan[1].restschuld_nach, 9598.0, places=2)
		self.assertAlmostEqual(doc._plan[2].restschuld_nach, 9394.0, places=2)

	def test_restschuld_nach_with_sondertilgung(self):
		doc = _make_fake_doc(
			anfangs_restschuld=10_000.0,
			rates=[
				{
					"faelligkeitsdatum": datetime.date(2026, 1, 31),
					"zinsanteil": 50,
					"tilgungsanteil": 200,
					"sondertilgung": 1000,
				},
			],
		)
		kv_mod.Kreditvertrag._compute_zeilen_summen(doc)
		kv_mod.Kreditvertrag._compute_restschuld_nach(doc)
		self.assertAlmostEqual(doc._plan[0].restschuld_nach, 8800.0, places=2)
		self.assertAlmostEqual(doc._plan[0].gesamtbetrag, 1250.0, places=2)

	def test_gesamtbetrag_sums_components(self):
		doc = _make_fake_doc(
			rates=[
				{
					"faelligkeitsdatum": datetime.date(2026, 1, 31),
					"zinsanteil": 100,
					"tilgungsanteil": 200,
					"sondertilgung": 50,
				}
			],
		)
		kv_mod.Kreditvertrag._compute_zeilen_summen(doc)
		self.assertAlmostEqual(doc._plan[0].gesamtbetrag, 350.0, places=2)


class TestComputeStatus(unittest.TestCase):
	def test_neuer_vertrag_mit_zukunftsplan_ist_aktiv(self):
		"""Kritischer Test: ein Kreditvertrag mit Vollplan, wo letzte Restschuld=0 ist,
		darf NICHT sofort als Abgelöst markiert werden — solange die Raten ungebucht sind.
		"""
		future = datetime.date.today() + datetime.timedelta(days=30)
		doc = _make_fake_doc(
			anfangs_restschuld=1000.0,
			rates=[
				{
					"faelligkeitsdatum": future,
					"zinsanteil": 0,
					"tilgungsanteil": 1000,
					"sondertilgung": 0,
					"journal_entry": None,  # ungebucht!
				},
			],
		)
		kv_mod.Kreditvertrag._compute_zeilen_summen(doc)
		kv_mod.Kreditvertrag._compute_restschuld_nach(doc)
		# _compute_plausibilitaet ist abhängig von DB — wir setzen es manuell:
		doc.aktuelle_restschuld = 1000.0  # nichts gebucht → volle Restschuld
		kv_mod.Kreditvertrag._compute_status(doc)
		self.assertEqual(doc.status, STATUS_AKTIV)

	def test_alle_gebucht_und_restschuld_null_ist_abgeloest(self):
		past = datetime.date.today() - datetime.timedelta(days=30)
		doc = _make_fake_doc(
			anfangs_restschuld=1000.0,
			rates=[
				{
					"faelligkeitsdatum": past,
					"zinsanteil": 0,
					"tilgungsanteil": 1000,
					"sondertilgung": 0,
					"journal_entry": "JV-1",  # gebucht!
				},
			],
		)
		kv_mod.Kreditvertrag._compute_zeilen_summen(doc)
		kv_mod.Kreditvertrag._compute_restschuld_nach(doc)
		doc.aktuelle_restschuld = 0.0
		kv_mod.Kreditvertrag._compute_status(doc)
		self.assertEqual(doc.status, STATUS_ABGELOEST)


class TestParseCsvAmount(unittest.TestCase):
	def test_parse_amount_negative(self):
		# Negative Beträge können in CSV vorkommen (Eingang vs. Ausgang) — wir akzeptieren sie
		self.assertEqual(_parse_amount("-100,50"), -100.5)


class TestImportable(unittest.TestCase):
	def test_module_imports(self):
		"""Smoke: Modul lädt ohne ImportError."""
		from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (  # noqa: F401
			Kreditvertrag,
			_create_journal_entry_for_rate,
			_candidate_rates,
			link_bank_transaction_to_kreditvertrag_rate,
			get_open_rates_for_match,
			assign_kreditrate,
			update_statuses_for_list,
			on_journal_entry_cancel,
		)
		from hausverwaltung.hausverwaltung.doctype.kreditrate.kreditrate import Kreditrate  # noqa: F401


# ============================================================================
# Integration Tests (IntegrationTestCase, brauchen Site-Daten)
# ============================================================================


def _find_test_company() -> str | None:
	"""Holt eine Company. Bevorzugt 'Hausverwaltung Peters', fällt sonst auf erste."""
	for candidate in ("Hausverwaltung Peters", "Test Company"):
		if frappe.db.exists("Company", candidate):
			return candidate
	row = frappe.db.get_value("Company", {}, "name")
	return row


def _find_account(company: str, root_type: str, exclude_account_type: str | None = None) -> str | None:
	filters = {"company": company, "is_group": 0, "root_type": root_type, "disabled": 0}
	rows = frappe.get_all("Account", filters=filters, pluck="name", limit=20)
	for name in rows:
		acc_type = frappe.db.get_value("Account", name, "account_type") or ""
		if exclude_account_type and acc_type == exclude_account_type:
			continue
		return name
	return None


def _find_bank_account(company: str) -> str | None:
	rows = frappe.get_all(
		"Bank Account",
		filters={"company": company, "disabled": 0, "is_company_account": 1},
		pluck="name",
		limit=1,
	)
	if rows:
		return rows[0]
	rows = frappe.get_all("Bank Account", filters={"company": company, "disabled": 0}, pluck="name", limit=1)
	return rows[0] if rows else None


def _find_supplier() -> str | None:
	return frappe.db.get_value("Supplier", {"disabled": 0}, "name")


def _make_test_kreditvertrag(
	company: str,
	supplier: str,
	bank_account: str,
	darlehenskonto: str,
	zinsaufwandskonto: str,
	anfangs_restschuld: float = 10_000.0,
	rate_date: datetime.date | None = None,
	zins: float = 50.0,
	tilgung: float = 200.0,
	sondertilgung: float = 0.0,
) -> object:
	rate_date = rate_date or datetime.date(2026, 5, 31)
	kv = frappe.new_doc("Kreditvertrag")
	kv.bezeichnung = f"TEST Kreditvertrag {datetime.datetime.now().timestamp()}"
	kv.company = company
	kv.lieferant = supplier
	kv.bank_account = bank_account
	kv.darlehenskonto = darlehenskonto
	kv.zinsaufwandskonto = zinsaufwandskonto
	kv.anfangs_restschuld = anfangs_restschuld
	kv.append(
		"plan",
		{
			"faelligkeitsdatum": rate_date,
			"zinsanteil": zins,
			"tilgungsanteil": tilgung,
			"sondertilgung": sondertilgung,
		},
	)
	kv.insert(ignore_permissions=True)
	return kv


def _make_test_bank_transaction(bank_account: str, posting_date, amount: float) -> object:
	bt = frappe.new_doc("Bank Transaction")
	bt.date = posting_date
	bt.bank_account = bank_account
	bt.withdrawal = abs(amount)
	bt.deposit = 0
	bt.description = "TEST Kreditrate"
	bt.insert(ignore_permissions=True)
	bt.submit()
	return bt


class TestKreditvertragIntegration(unittest.TestCase):
	"""Integration: JE-Erstellung, PLE-Negativ, Rollback, Storno.

	Bewusst ``unittest.TestCase`` statt ``IntegrationTestCase``: letzteres würde
	automatische Test-Record-Dependency-Erstellung anwerfen (Fiscal Year etc.),
	was auf einer laufenden Site mit echten Daten kollidiert. Stattdessen
	nutzen wir die existierenden Site-Daten und isolieren Tests via
	Savepoint/Rollback in setUp/tearDown.
	"""

	_savepoint_counter = 0

	def setUp(self):
		# Eindeutiger Savepoint-Name pro Test, damit Nested-Calls nicht kollidieren
		TestKreditvertragIntegration._savepoint_counter += 1
		self._sp_name = f"kv_test_sp_{TestKreditvertragIntegration._savepoint_counter}"
		frappe.db.savepoint(self._sp_name)
		frappe.set_user("Administrator")

	def tearDown(self):
		try:
			frappe.db.rollback(save_point=self._sp_name)
		except Exception:
			frappe.db.rollback()

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Frappe-Init muss laufen, damit frappe.db verfügbar ist — bench
		# run-tests sorgt dafür, hier nur Defensiv-Check.
		if not getattr(frappe, "local", None) or not getattr(frappe.local, "db", None):
			raise unittest.SkipTest("Frappe-DB nicht initialisiert.")
		cls.company = _find_test_company()
		if not cls.company:
			raise unittest.SkipTest("Keine Company auf der Site — Integration-Tests skipped.")
		cls.darlehenskonto = _find_account(cls.company, "Liability", exclude_account_type="Payable")
		cls.zinsaufwandskonto = _find_account(cls.company, "Expense")
		cls.bank_account = _find_bank_account(cls.company)
		cls.supplier = _find_supplier()
		if not all([cls.darlehenskonto, cls.zinsaufwandskonto, cls.bank_account, cls.supplier]):
			raise unittest.SkipTest(
				f"Site-Daten unvollständig (darlehenskonto={cls.darlehenskonto}, "
				f"zins={cls.zinsaufwandskonto}, bank={cls.bank_account}, supplier={cls.supplier})."
			)

	def _make_kv(self, **kwargs):
		return _make_test_kreditvertrag(
			company=self.company,
			supplier=self.supplier,
			bank_account=self.bank_account,
			darlehenskonto=self.darlehenskonto,
			zinsaufwandskonto=self.zinsaufwandskonto,
			**kwargs,
		)

	# ------------------------------------------------------------------
	# JE-Erstellung
	# ------------------------------------------------------------------

	def test_create_journal_entry_with_split(self):
		"""JE hat 3 Account-Zeilen: Bank-Cr, Zins-Dr, Darlehen-Dr mit Party."""
		kv = self._make_kv(zins=50, tilgung=200, sondertilgung=0)
		rate = kv.plan[0]
		je = _create_journal_entry_for_rate(kv, rate, posting_date=datetime.date(2026, 6, 1))
		self.assertEqual(je.docstatus, 1, "JE muss submitted sein")
		# 3 Account-Rows: Bank (credit), Zins (debit), Darlehen (debit)
		self.assertEqual(len(je.accounts), 3)
		bank_rows = [a for a in je.accounts if a.credit_in_account_currency > 0]
		debit_rows = [a for a in je.accounts if a.debit_in_account_currency > 0]
		self.assertEqual(len(bank_rows), 1)
		self.assertEqual(len(debit_rows), 2)
		self.assertAlmostEqual(bank_rows[0].credit_in_account_currency, 250.0, places=2)
		# Party muss auf der Darlehenskonto-Zeile sitzen
		darlehen_row = next(a for a in je.accounts if a.account == self.darlehenskonto)
		self.assertEqual(darlehen_row.party_type, "Supplier")
		self.assertEqual(darlehen_row.party, self.supplier)
		# user_remark + custom_remark gesetzt (sonst überschreibt ERPNext)
		self.assertTrue(je.user_remark)
		self.assertEqual(je.custom_remark, 1)

	def test_create_journal_entry_skips_zero_interest(self):
		"""Bei zinsanteil=0 wird die Zins-Zeile weggelassen."""
		kv = self._make_kv(zins=0, tilgung=500, sondertilgung=0)
		rate = kv.plan[0]
		je = _create_journal_entry_for_rate(kv, rate, posting_date=datetime.date(2026, 6, 1))
		self.assertEqual(len(je.accounts), 2, "Nur Bank + Darlehen, keine Zinszeile")

	def test_create_journal_entry_includes_sondertilgung_in_tilgung_row(self):
		"""Sondertilgung wird zusammen mit Tilgung auf das Darlehenskonto gebucht."""
		kv = self._make_kv(zins=10, tilgung=100, sondertilgung=500)
		rate = kv.plan[0]
		je = _create_journal_entry_for_rate(kv, rate, posting_date=datetime.date(2026, 6, 1))
		darlehen_row = next(a for a in je.accounts if a.account == self.darlehenskonto)
		self.assertAlmostEqual(darlehen_row.debit_in_account_currency, 600.0, places=2)

	# ------------------------------------------------------------------
	# Payment Ledger Negativ-Test
	# ------------------------------------------------------------------

	def test_no_payment_ledger_entry_for_journal_entry(self):
		"""Da darlehenskonto.account_type leer ist (nicht 'Payable'), darf KEIN
		Payment Ledger Entry für den JE entstehen."""
		kv = self._make_kv()
		rate = kv.plan[0]
		je = _create_journal_entry_for_rate(kv, rate, posting_date=datetime.date(2026, 6, 1))
		ple_exists = frappe.db.exists(
			"Payment Ledger Entry",
			{"voucher_type": "Journal Entry", "voucher_no": je.name},
		)
		self.assertFalse(
			ple_exists,
			f"Kein Payment Ledger Entry erwartet, aber gefunden: {ple_exists}",
		)

	# ------------------------------------------------------------------
	# Rollback bei Reconcile-Fehler
	# ------------------------------------------------------------------

	def test_rollback_on_reconcile_failure_cancels_je(self):
		"""Wenn reconcile_voucher_with_bt nach JE-Submit fehlschlägt:
		- JE wird storniert (oder rollback'd)
		- Rate bleibt unverknüpft
		- Kein verwaister submitted JE."""
		kv = self._make_kv()
		rate = kv.plan[0]
		bt = _make_test_bank_transaction(
			self.bank_account, posting_date=rate.faelligkeitsdatum, amount=rate.gesamtbetrag
		)

		# reconcile_voucher_with_bt patchen, sodass es nach JE-Submit fliegt
		import hausverwaltung.hausverwaltung.utils.payment_auto_match as pam

		with patch.object(pam, "reconcile_voucher_with_bt", side_effect=RuntimeError("simulated")):
			with self.assertRaises(RuntimeError):
				link_bank_transaction_to_kreditvertrag_rate(
					bank_account=self.bank_account,
					posting_date=rate.faelligkeitsdatum,
					amount=rate.gesamtbetrag,
					bank_transaction=bt.name,
					supplier=self.supplier,
				)

		# Rate muss noch offen sein
		rate.reload()
		self.assertIsNone(rate.get("journal_entry"), "Rate darf nicht verlinkt sein")
		self.assertIsNone(rate.get("bank_transaction"))

		# Kein submitted JE für diese Kreditrate hängengeblieben — wir prüfen das
		# über Remarks, weil der Name aleatorisch ist
		stuck = frappe.db.sql(
			"""
			SELECT name FROM `tabJournal Entry`
			WHERE docstatus=1
			  AND user_remark LIKE %(remark)s
			""",
			{"remark": f"%{kv.bezeichnung}%"},
		)
		self.assertFalse(stuck, f"Verwaister submitted JE gefunden: {stuck}")

	# ------------------------------------------------------------------
	# Storno-Hook
	# ------------------------------------------------------------------

	def test_journal_entry_cancel_frees_rate(self):
		"""Nach JE.cancel() ist die Rate wieder match-bar."""
		kv = self._make_kv()
		rate = kv.plan[0]
		je = _create_journal_entry_for_rate(kv, rate, posting_date=rate.faelligkeitsdatum)

		# manuell verlinken (sonst hat der Storno-Hook nichts zu tun)
		rate.db_set("journal_entry", je.name, update_modified=False)

		# Storno → on_cancel-Hook feuert
		je_doc = frappe.get_doc("Journal Entry", je.name)
		je_doc.cancel()

		rate.reload()
		self.assertIsNone(rate.get("journal_entry"), "Rate muss nach JE-Cancel wieder frei sein")

	# ------------------------------------------------------------------
	# CSV-Import
	# ------------------------------------------------------------------

	def _upload_csv(self, content: str) -> str:
		"""Legt ein File-Dokument mit dem gegebenen CSV-Inhalt an und gibt file_url zurück."""
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": f"test_kreditplan_{datetime.datetime.now().timestamp()}.csv",
			"is_private": 1,
			"content": content,
		})
		file_doc.insert(ignore_permissions=True)
		return file_doc.file_url

	def test_plan_csv_import_german_format_extend(self):
		"""Standard-CSV mit Semicolon + Komma-Beträgen wird korrekt importiert."""
		kv = self._make_kv(anfangs_restschuld=10_000.0)
		# Default-Rate aus _make_kv löschen, sonst kollidieren Daten
		kv.set("plan", [])
		kv.save(ignore_permissions=True)

		csv_content = (
			"datum;zinsanteil;tilgungsanteil;sondertilgung\n"
			"2026-06-30;50,00;200,00;0\n"
			"2026-07-31;48,00;202,00;0\n"
			"2026-08-31;46,00;204,00;500,00\n"
		)
		file_url = self._upload_csv(csv_content)

		result = kv.plan_csv_import(file_url=file_url, mode="extend")
		self.assertEqual(result["added"], 3)
		self.assertEqual(result["skipped"], 0)

		kv.reload()
		self.assertEqual(len(kv.plan), 3)
		# Plan ist nach Datum sortiert
		self.assertEqual(str(kv.plan[0].faelligkeitsdatum), "2026-06-30")
		self.assertEqual(str(kv.plan[2].faelligkeitsdatum), "2026-08-31")
		# Beträge korrekt geparsed (deutsche Notation)
		self.assertAlmostEqual(kv.plan[0].zinsanteil, 50.0, places=2)
		self.assertAlmostEqual(kv.plan[2].sondertilgung, 500.0, places=2)
		# gesamtbetrag wurde berechnet
		self.assertAlmostEqual(kv.plan[2].gesamtbetrag, 750.0, places=2)
		# restschuld_nach läuft kumulativ ab anfangs_restschuld
		# Zeile 1: 10000 - 200 = 9800
		self.assertAlmostEqual(kv.plan[0].restschuld_nach, 9800.0, places=2)
		# Zeile 3: 9598 - 204 - 500 = 8894
		self.assertAlmostEqual(kv.plan[2].restschuld_nach, 8894.0, places=2)

	def test_plan_csv_import_replace_mode_clears_existing(self):
		"""mode='replace' wirft den bestehenden Plan weg."""
		kv = self._make_kv()
		self.assertEqual(len(kv.plan), 1)  # 1 Default-Rate aus _make_kv
		csv_content = (
			"datum,zinsanteil,tilgungsanteil\n"
			"2027-01-31,10.00,100.00\n"
		)
		file_url = self._upload_csv(csv_content)
		result = kv.plan_csv_import(file_url=file_url, mode="replace")
		self.assertEqual(result["added"], 1)
		kv.reload()
		self.assertEqual(len(kv.plan), 1)
		self.assertEqual(str(kv.plan[0].faelligkeitsdatum), "2027-01-31")

	def test_plan_csv_import_invalid_file_url_throws(self):
		"""Nicht-existente file_url → klare Fehlermeldung (nicht silently fail)."""
		kv = self._make_kv()
		with self.assertRaises(Exception) as ctx:
			kv.plan_csv_import(file_url="/files/does-not-exist-12345.csv", mode="extend")
		self.assertIn("nicht gefunden", str(ctx.exception).lower())

	# ------------------------------------------------------------------
	# Plausibilität — Plan-Tilgung vs. verlinkte JE-Tilgung
	# ------------------------------------------------------------------

	def _book_rate(self, kv, rate):
		"""Erzeugt einen JE für die Rate und verlinkt ihn (wie der Bankimport)."""
		je = _create_journal_entry_for_rate(kv, rate, posting_date=rate.faelligkeitsdatum)
		rate.db_set("journal_entry", je.name, update_modified=False)
		return je

	def test_plausibilitaet_geteiltes_darlehenskonto(self):
		"""Zwei Kreditverträge auf DEMSELBEN Darlehenskonto: gl_getilgt jedes
		Vertrags zählt nur seine eigenen verlinkten JEs — nicht die des anderen."""
		kv_a = self._make_kv(anfangs_restschuld=10_000.0, zins=50, tilgung=200, sondertilgung=0)
		kv_b = self._make_kv(anfangs_restschuld=20_000.0, zins=80, tilgung=300, sondertilgung=0)
		# beide nutzen self.darlehenskonto (gleiches Konto)
		self.assertEqual(kv_a.darlehenskonto, kv_b.darlehenskonto)

		self._book_rate(kv_a, kv_a.plan[0])  # Tilgung 200
		self._book_rate(kv_b, kv_b.plan[0])  # Tilgung 300

		kv_a.reload()
		kv_b.reload()
		kv_a._compute_plausibilitaet()
		kv_b._compute_plausibilitaet()

		# Jeder Vertrag sieht nur seine eigene Tilgung
		self.assertAlmostEqual(kv_a.plan_getilgt, 200.0, places=2)
		self.assertAlmostEqual(kv_a.gl_getilgt, 200.0, places=2)
		self.assertAlmostEqual(kv_a.restschuld_abweichung, 0.0, places=2)

		self.assertAlmostEqual(kv_b.plan_getilgt, 300.0, places=2)
		self.assertAlmostEqual(kv_b.gl_getilgt, 300.0, places=2)
		self.assertAlmostEqual(kv_b.restschuld_abweichung, 0.0, places=2)

		# Der Whole-Account-Saldo trägt dagegen BEIDE Kredite (500 Soll gesamt) —
		# darum ist er nur Info und nicht der Wächter.
		self.assertNotAlmostEqual(kv_a.gl_getilgt, abs(kv_a.gl_saldo_darlehenskonto), places=2)

	def test_plausibilitaet_abweichung_null_nach_normaler_buchung(self):
		"""Nach normaler Buchung stimmen Plan-Tilgung und GL-Tilgung überein."""
		kv = self._make_kv(anfangs_restschuld=5_000.0, zins=10, tilgung=100, sondertilgung=50)
		self._book_rate(kv, kv.plan[0])
		kv.reload()
		kv._compute_plausibilitaet()
		# Tilgung + Sondertilgung = 150
		self.assertAlmostEqual(kv.plan_getilgt, 150.0, places=2)
		self.assertAlmostEqual(kv.gl_getilgt, 150.0, places=2)
		self.assertAlmostEqual(kv.restschuld_abweichung, 0.0, places=2)
		self.assertAlmostEqual(kv.aktuelle_restschuld, 4_850.0, places=2)

	def test_plausibilitaet_ohne_gebuchte_raten(self):
		"""KV mit nur ungebuchten Raten: keine SQL-IN-()-Exception, alles 0."""
		kv = self._make_kv(anfangs_restschuld=8_000.0)
		# Default-Rate ist ungebucht (kein journal_entry)
		kv._compute_plausibilitaet()
		self.assertAlmostEqual(kv.plan_getilgt, 0.0, places=2)
		self.assertAlmostEqual(kv.gl_getilgt, 0.0, places=2)
		self.assertAlmostEqual(kv.restschuld_abweichung, 0.0, places=2)
		self.assertAlmostEqual(kv.aktuelle_restschuld, 8_000.0, places=2)


if __name__ == "__main__":
	unittest.main()
