import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

class CustomSalesInvoice(SalesInvoice):

    def validate(self):
        super().validate()
        if self.is_return:
            self.fix_return_stock_qty()

    def before_submit(self):
        if self.is_return:
            self.fix_return_stock_qty()

    def validate_update_after_submit(self):
        # selling_price_list is legitimately changed by the branch price-list JS
        # before submission (without an intermediate save), so exempt it from the
        # after-submit change check by temporarily aligning it with the DB value.
        if self.docstatus != 1:
            return super().validate_update_after_submit()

        db_pl = frappe.db.get_value("Sales Invoice", self.name, "selling_price_list")
        current_pl = self.selling_price_list
        self.selling_price_list = db_pl
        try:
            super().validate_update_after_submit()
        finally:
            self.selling_price_list = current_pl

    def fix_return_stock_qty(self):
        for item in self.items:
            if item.stock_qty and item.stock_qty > 0:
                item.stock_qty = item.stock_qty * -1
