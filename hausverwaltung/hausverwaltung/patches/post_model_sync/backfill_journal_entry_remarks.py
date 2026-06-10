"""Backfill Journal Entry remarks into headers and GL Entries.

Some imported Journal Entries have the intended text in `user_remark`, while
`remark`, `custom_remark`, and the generated GL Entry `remarks` are empty. The
General Ledger reports read GL Entry remarks, so copy the user text there.
"""

from __future__ import annotations

import frappe


def execute():
	header_pre = _count_headers_to_update()
	gl_pre = _count_gl_entries_to_update()

	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET remark = user_remark, custom_remark = 1
		WHERE docstatus = 1
		  AND COALESCE(TRIM(user_remark), '') <> ''
		  AND (
		      COALESCE(remark, '') <> user_remark
		      OR COALESCE(custom_remark, 0) = 0
		  )
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		SET gl.remarks = je.user_remark
		WHERE gl.voucher_type = 'Journal Entry'
		  AND gl.docstatus = 1
		  AND gl.is_cancelled = 0
		  AND je.docstatus = 1
		  AND COALESCE(TRIM(je.user_remark), '') <> ''
		  AND COALESCE(gl.remarks, '') <> je.user_remark
		"""
	)

	if header_pre or gl_pre:
		frappe.db.commit()

	header_post = _count_headers_to_update()
	gl_post = _count_gl_entries_to_update()
	frappe.log(
		f"[backfill_journal_entry_remarks] updated {header_pre - header_post} Journal Entry "
		f"headers and {gl_pre - gl_post} GL Entry remarks; remaining headers={header_post}, "
		f"gl_entries={gl_post}"
	)


def _count_headers_to_update() -> int:
	return frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabJournal Entry`
		WHERE docstatus = 1
		  AND COALESCE(TRIM(user_remark), '') <> ''
		  AND (
		      COALESCE(remark, '') <> user_remark
		      OR COALESCE(custom_remark, 0) = 0
		  )
		"""
	)[0][0]


def _count_gl_entries_to_update() -> int:
	return frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		WHERE gl.voucher_type = 'Journal Entry'
		  AND gl.docstatus = 1
		  AND gl.is_cancelled = 0
		  AND je.docstatus = 1
		  AND COALESCE(TRIM(je.user_remark), '') <> ''
		  AND COALESCE(gl.remarks, '') <> je.user_remark
		"""
	)[0][0]
