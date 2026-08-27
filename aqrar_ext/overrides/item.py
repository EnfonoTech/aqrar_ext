"""Item controller override (hooks.override_doctype_class).

CR-031 — lock the default UOM once stock movements exist, with an audited
admin override.
CR-020 / CR-030 — default the naming series from the Item Group, and route
customer-specific ("temporary") items onto their own TM- series.
"""

import frappe
from erpnext.stock.doctype.item.item import Item
from frappe import _

TEMPORARY_ITEM_SERIES = "TM-.#####"
CUSTOMER_SPECIFIC = "Customer-Specific"


class CustomItem(Item):
	def before_naming(self):
		self.set_default_naming_series()
		# ERPNext's Item has no before_naming today; delegate defensively without
		# relying on getattr(), which Document's attribute machinery can mask.
		for klass in type(self).__mro__[1:]:
			parent_hook = klass.__dict__.get("before_naming")
			if parent_hook:
				parent_hook(self)
				break

	def validate(self):
		super().validate()
		# Item.validate() already ran the core validate_uom() (variant/template
		# UOM consistency). The lock is an additional, Aqrar-specific rule.
		self.validate_uom_lock()

	# ------------------------------------------------------------------ naming

	def set_default_naming_series(self):
		"""CR-020 / CR-030: pick the naming series when the user left it blank."""
		if not self.meta.has_field("naming_series") or self.get("naming_series"):
			return

		if frappe.db.get_single_value("Stock Settings", "item_naming_by") != "Naming Series":
			return

		series = None

		# CR-030 — customer-specific / temporary items get the TM- series.
		if (
			self.meta.has_field("custom_item_visibility")
			and self.get("custom_item_visibility") == CUSTOMER_SPECIFIC
		):
			series = TEMPORARY_ITEM_SERIES

		# CR-020 — otherwise fall back to the Item Group default.
		if not series and self.get("item_group"):
			if frappe.db.has_column("Item Group", "custom_default_item_naming_series"):
				series = frappe.db.get_value(
					"Item Group", self.item_group, "custom_default_item_naming_series"
				)

		if not series:
			return

		options = (self.meta.get_field("naming_series").options or "").split("\n")
		if series not in options:
			# Naming Series options are maintained centrally; adding an unknown
			# value here would fail validation, so surface it instead.
			frappe.msgprint(
				_("Naming series {0} is not available on Item — using the default series.").format(
					frappe.bold(series)
				),
				alert=True,
				indicator="orange",
			)
			return

		self.naming_series = series

	# -------------------------------------------------------------------- UOM

	def validate_uom_lock(self):
		"""CR-031: block a stock UOM change once stock movements exist."""
		if self.is_new():
			return

		old_uom = frappe.db.get_value("Item", self.name, "stock_uom")
		if not old_uom or old_uom == self.stock_uom:
			return

		sle_count = frappe.db.count(
			"Stock Ledger Entry", filters={"item_code": self.name, "is_cancelled": 0}
		)
		if not sle_count:
			return

		if not self._can_override_uom():
			frappe.throw(
				_(
					"Default UOM cannot be changed after stock transactions exist. "
					"This item has {0} stock ledger entries. "
					"Contact your administrator to override."
				).format(sle_count),
				title=_("UOM Locked"),
			)

		if not self.meta.has_field("custom_uom_override_reason"):
			frappe.throw(
				_("UOM override audit fields are not installed. Run bench migrate and retry."),
				title=_("Override Not Configured"),
			)

		# Require a FRESH reason — a stale one left over from a previous
		# override must not silently authorise this change.
		db_reason = frappe.db.get_value("Item", self.name, "custom_uom_override_reason")
		if not self.custom_uom_override_reason or self.custom_uom_override_reason == db_reason:
			frappe.throw(
				_(
					"Please use the 'Override UOM (Admin)' button and provide a new reason "
					"before changing the Default UOM."
				),
				title=_("Override Reason Required"),
			)

		user = frappe.session.user
		if self.meta.has_field("custom_uom_overridden_by"):
			self.custom_uom_overridden_by = user
		if self.meta.has_field("custom_uom_override_date"):
			self.custom_uom_override_date = frappe.utils.now_datetime()

		trail = _("UOM Override by {0} | Old UOM: {1} | New UOM: {2} | Reason: {3}").format(
			user, old_uom, self.stock_uom, self.custom_uom_override_reason
		)
		if self.meta.has_field("custom_uom_override_audit_trail"):
			previous = self.get("custom_uom_override_audit_trail") or ""
			self.custom_uom_override_audit_trail = (previous + "\n" + trail).strip()

		self.add_comment("Info", trail)

	@staticmethod
	def _can_override_uom():
		user = frappe.session.user
		if user == "Administrator":
			return True
		return "System Manager" in frappe.get_roles(user)
