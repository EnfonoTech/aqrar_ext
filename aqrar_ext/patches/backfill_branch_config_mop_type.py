"""The Branch Configuration payment row carried a hand-typed `type` Select whose
options (Cash/Bank/Card/Credit/General) did not even match core's Mode of
Payment types (Cash/Bank/General/Phone), so the column could disagree with the
mode it described. It now fetches from `mode_of_payment.type`; backfill the
rows that were typed by hand.
"""

import frappe


def execute():
	table = "Branch Configuration Mode of Payment"
	if not frappe.db.table_exists(table):
		return

	frappe.db.sql(
		"""
		UPDATE `tabBranch Configuration Mode of Payment` bcm
		INNER JOIN `tabMode of Payment` mop ON mop.name = bcm.mode_of_payment
		SET bcm.type = mop.type
		WHERE bcm.mode_of_payment IS NOT NULL
		  AND (bcm.type IS NULL OR bcm.type != mop.type)
		"""
	)
