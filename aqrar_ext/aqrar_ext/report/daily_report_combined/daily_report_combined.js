// Copyright (c) 2026, Aravind R and contributors
// For license information, please see license.txt

frappe.query_reports["Daily Report Combined"] = {
	"filters" : [
		{
			"fieldname": "date",
			"label": "Date",
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname": "type",
			"label": "Type",
			"fieldtype": "Select",
			"options": "\nCash Sales\nCard Sales\nCredit Sales\nCash Purchases\nCard Purchases\nCredit Purchases\nSales Return Cash\nSales Return Card\nSales Return Credit\nSales Returns\nPurchase Return Cash\nPurchase Return Card\nPurchase Return Credit\nPurchase Returns\nCustomer Receipts\nSupplier Payments\nBank Receipts\nBank Payments\nCash Receipts\nCash Payments",
		}
	]
};
