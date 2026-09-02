"""Branch Configuration was created without an autoname, so existing rows carry
random hashes (e.g. `8mhckq1tlu`). The DocType now uses `field:branch`; rename
the old rows so the list is readable and links stay meaningful.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Branch Configuration"):
		return

	for name, branch in frappe.db.sql(
		"""SELECT name, branch FROM `tabBranch Configuration`
		   WHERE branch IS NOT NULL AND branch != '' AND name != branch"""
	):
		if frappe.db.exists("Branch Configuration", branch):
			# a row already owns that name — leave the duplicate for a human
			frappe.logger("aqrar_ext").warning(
				f"Branch Configuration {name}: '{branch}' already taken, not renamed"
			)
			continue
		try:
			frappe.rename_doc("Branch Configuration", name, branch, force=True, show_alert=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Branch Configuration rename failed")
