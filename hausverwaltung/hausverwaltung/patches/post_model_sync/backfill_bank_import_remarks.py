"""Backfill `remark`/`remarks` und `custom_remark`/`custom_remarks` auf
historischen Bank-Entry Journal Entries und vom Bank-Import erzeugten
Payment Entries.

Vor dem Code-Fix in ``utils/payment_auto_match.py`` wurde der
Verwendungszweck der Bank-Zeile zwar in ``user_remark`` (JE) bzw.
``remarks`` (PE) gespeichert — direkt nach dem Insert hat ERPNexts
Auto-Generierungs­logik den letztlich angezeigten Text aber überschrieben:

* JE: ``create_remarks()`` setzt ``remark`` auf ``"Reference #X dated Y"``,
  woraus dann ``tabGL Entry.remarks`` abgeleitet wird.
* PE: ``set_remarks()`` setzt ``remarks`` auf
  ``"Betrag EUR X bezahlt an Y\\nTransaktion Referenznummer Z"``.

Dieser Patch zieht die Anzeige auf den echten Verwendungszweck nach und
setzt ``custom_remark`` / ``custom_remarks`` auf 1, damit ein späteres
Save (z.B. nach UI-Bearbeitung) die Werte nicht erneut überschreibt.

Bewusst NICHT in ``patches.txt`` eingetragen — manuell ausführen pro
Umgebung:

    bench --site <site> execute \\
      hausverwaltung.hausverwaltung.patches.post_model_sync.backfill_bank_import_remarks.execute

Idempotent: alle UPDATEs filtern auf tatsächliche Differenz, erneuter
Lauf ist ein No-op.
"""

import frappe


def execute():
	_backfill_journal_entries()
	_backfill_payment_entries()


def _backfill_journal_entries() -> None:
	je_pre = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabJournal Entry`
		WHERE voucher_type = 'Bank Entry'
		  AND docstatus = 1
		  AND user_remark IS NOT NULL AND user_remark <> ''
		  AND remark <> user_remark
		"""
	)[0][0]
	gl_pre = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		WHERE gl.voucher_type = 'Journal Entry'
		  AND je.voucher_type = 'Bank Entry'
		  AND je.docstatus = 1
		  AND gl.is_cancelled = 0
		  AND gl.remarks <> je.user_remark
		  AND je.user_remark IS NOT NULL AND je.user_remark <> ''
		"""
	)[0][0]

	frappe.log(
		f"[backfill_bank_remarks] Journal Entry: {je_pre} JE-Header, {gl_pre} GL-Zeilen abweichend vom Verwendungszweck"
	)

	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET remark = user_remark, custom_remark = 1
		WHERE voucher_type = 'Bank Entry'
		  AND docstatus = 1
		  AND user_remark IS NOT NULL AND user_remark <> ''
		  AND remark <> user_remark
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		SET gl.remarks = je.remark
		WHERE gl.voucher_type = 'Journal Entry'
		  AND je.voucher_type = 'Bank Entry'
		  AND je.docstatus = 1
		  AND gl.is_cancelled = 0
		  AND gl.remarks <> je.remark
		"""
	)

	frappe.db.commit()

	je_post = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabJournal Entry`
		WHERE voucher_type = 'Bank Entry'
		  AND docstatus = 1
		  AND user_remark IS NOT NULL AND user_remark <> ''
		  AND remark <> user_remark
		"""
	)[0][0]
	gl_post = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		WHERE gl.voucher_type = 'Journal Entry'
		  AND je.voucher_type = 'Bank Entry'
		  AND je.docstatus = 1
		  AND gl.is_cancelled = 0
		  AND gl.remarks <> je.remark
		"""
	)[0][0]
	frappe.log(
		f"[backfill_bank_remarks] Journal Entry: header backfill schloss "
		f"{je_pre - je_post} (übrig: {je_post}), GL backfill schloss "
		f"{gl_pre - gl_post} (übrig: {gl_post})"
	)


def _backfill_payment_entries() -> None:
	pe_pre = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabPayment Entry` pe
		JOIN `tabBank Transaction Payments` btp
		     ON btp.payment_entry = pe.name
		    AND btp.payment_document = 'Payment Entry'
		JOIN `tabBankauszug Import Row` br
		     ON br.bank_transaction = btp.parent
		WHERE pe.docstatus = 1
		  AND pe.custom_remarks = 0
		  AND br.verwendungszweck IS NOT NULL AND br.verwendungszweck <> ''
		  AND pe.remarks <> br.verwendungszweck
		"""
	)[0][0]
	gl_pre = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry` gl
		JOIN `tabPayment Entry` pe ON pe.name = gl.voucher_no
		WHERE gl.voucher_type = 'Payment Entry'
		  AND pe.docstatus = 1
		  AND pe.custom_remarks = 1
		  AND gl.is_cancelled = 0
		  AND pe.remarks IS NOT NULL AND pe.remarks <> ''
		  AND gl.remarks <> pe.remarks
		"""
	)[0][0]

	frappe.log(
		f"[backfill_bank_remarks] Payment Entry: {pe_pre} PE-Header, {gl_pre} GL-Zeilen abweichend vom Verwendungszweck"
	)

	frappe.db.sql(
		"""
		UPDATE `tabPayment Entry` pe
		JOIN `tabBank Transaction Payments` btp
		     ON btp.payment_entry = pe.name
		    AND btp.payment_document = 'Payment Entry'
		JOIN `tabBankauszug Import Row` br
		     ON br.bank_transaction = btp.parent
		SET pe.remarks = br.verwendungszweck, pe.custom_remarks = 1
		WHERE pe.docstatus = 1
		  AND pe.custom_remarks = 0
		  AND br.verwendungszweck IS NOT NULL AND br.verwendungszweck <> ''
		  AND pe.remarks <> br.verwendungszweck
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabGL Entry` gl
		JOIN `tabPayment Entry` pe ON pe.name = gl.voucher_no
		SET gl.remarks = pe.remarks
		WHERE gl.voucher_type = 'Payment Entry'
		  AND pe.docstatus = 1
		  AND pe.custom_remarks = 1
		  AND gl.is_cancelled = 0
		  AND pe.remarks IS NOT NULL AND pe.remarks <> ''
		  AND gl.remarks <> pe.remarks
		"""
	)

	frappe.db.commit()

	pe_post = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabPayment Entry` pe
		JOIN `tabBank Transaction Payments` btp
		     ON btp.payment_entry = pe.name
		    AND btp.payment_document = 'Payment Entry'
		JOIN `tabBankauszug Import Row` br
		     ON br.bank_transaction = btp.parent
		WHERE pe.docstatus = 1
		  AND pe.custom_remarks = 0
		  AND br.verwendungszweck IS NOT NULL AND br.verwendungszweck <> ''
		  AND pe.remarks <> br.verwendungszweck
		"""
	)[0][0]
	gl_post = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry` gl
		JOIN `tabPayment Entry` pe ON pe.name = gl.voucher_no
		WHERE gl.voucher_type = 'Payment Entry'
		  AND pe.docstatus = 1
		  AND pe.custom_remarks = 1
		  AND gl.is_cancelled = 0
		  AND pe.remarks IS NOT NULL AND pe.remarks <> ''
		  AND gl.remarks <> pe.remarks
		"""
	)[0][0]
	frappe.log(
		f"[backfill_bank_remarks] Payment Entry: header backfill schloss "
		f"{pe_pre - pe_post} (übrig: {pe_post}), GL backfill schloss "
		f"{gl_pre - gl_post} (übrig: {gl_post})"
	)
