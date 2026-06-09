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

    def fix_return_stock_qty(self):
        for item in self.items:
            if item.stock_qty and item.stock_qty > 0:
                item.stock_qty = item.stock_qty * -1
