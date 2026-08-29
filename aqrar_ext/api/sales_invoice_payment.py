"""Deprecated alias for :mod:`aqrar_ext.api.sales_invoice`.

This module previously held a byte-for-byte copy of the payment API, which
drifted (it wrote a different workflow state). It now re-exports the canonical
implementation so any client script still pointing here keeps working.
Prefer ``aqrar_ext.api.sales_invoice.*`` in new code.
"""

from aqrar_ext.api.sales_invoice import (
	create_pos_payments_for_invoice,
	get_payment_modes_with_account,
)

__all__ = ["create_pos_payments_for_invoice", "get_payment_modes_with_account"]
