import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class AqrarSettings(Document):
	def validate(self):
		if cint(self.get("auto_grn_backdate_days")) < 0:
			frappe.throw(_("GRN Backdate Days cannot be negative."))
