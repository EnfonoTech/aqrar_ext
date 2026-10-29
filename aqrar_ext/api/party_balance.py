"""Party balance for the document header (Sales / Purchase documents).

Same figure Payment Entry shows as "Party Balance": the party's ledger balance
(debits less credits, company currency) as of the document date. Unlike Payment
Entry it does not depend on "Show Party Balance" in Accounts Settings: the whole point
here is that it is always shown.
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_party_balance(party_type, party, company=None, date=None):
	"""Ledger balance of one Customer / Supplier, or None for any other party type."""
	if party_type not in ("Customer", "Supplier") or not party:
		return None

	# Whoever may open the party may see what it owes / is owed: the sales and
	# purchase users who enter these documents need not have General Ledger access.
	frappe.has_permission(party_type, "read", doc=party, throw=True)

	from erpnext.accounts.utils import get_balance_on

	return flt(
		get_balance_on(
			party_type=party_type,
			party=party,
			company=company,
			date=date,
			ignore_account_permission=True,
		)
	)
