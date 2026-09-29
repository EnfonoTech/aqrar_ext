"""Customer controller hooks (hooks.doc_events).

VAT Registration Number must be unique across customers — the same VAT
number on two different Customer records usually means a duplicate customer
or a data-entry mistake, and downstream VAT/e-invoicing reporting keys off
this number.

Users holding ALLOW_DUPLICATE_VAT_ROLE are exempt from the block: master-data
cleanup (e.g. merging duplicate customers, or a temporary placeholder)
sometimes needs two records to carry the same VAT number for a moment, and
that decision belongs to whoever holds the role, not to this check. They
still see the same duplicate flagged, just as a non-blocking popup
(frappe.msgprint) rather than a save-stopping error — so the collision isn't
silently missed, only permitted.

The exemption is checked against the actual `Has Role` assignment, not
`frappe.get_roles()`. The Administrator account is special-cased by the
framework to hold every role that exists, whether or not it was ever
assigned one explicitly, so `frappe.get_roles()` would silently exempt
Administrator from this check too, which is exactly the account this check
most needs to catch a real duplicate for.
"""

import frappe
from frappe import _, bold

ALLOW_DUPLICATE_VAT_ROLE = "Allow Duplicate VAT"


def validate_vat_uniqueness(doc, method=None):
	vat_number = (doc.get("custom_vat_registration_number") or "").strip()
	if not vat_number:
		return

	duplicate = frappe.db.get_value(
		"Customer",
		{
			"custom_vat_registration_number": vat_number,
			"name": ("!=", doc.name),
		},
		"name",
	)
	if not duplicate:
		return

	message = _("VAT Registration Number {0} is already used by customer {1}.").format(
		bold(vat_number), bold(duplicate)
	)

	is_exempt = frappe.db.exists(
		"Has Role", {"parent": frappe.session.user, "role": ALLOW_DUPLICATE_VAT_ROLE}
	)
	if is_exempt:
		frappe.msgprint(message, title=_("Duplicate VAT Registration Number"), indicator="orange")
	else:
		frappe.throw(message, title=_("Duplicate VAT Registration Number"))
