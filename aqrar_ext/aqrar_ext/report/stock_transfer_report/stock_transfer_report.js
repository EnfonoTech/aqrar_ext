// Copyright (c) 2026, Enfono and contributors
// For license information, please see license.txt

frappe.query_reports["Stock Transfer Report"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
        },
        {
            "fieldname": "stock_entry",
            "label": __("Stock Entry"),
            "fieldtype": "Link",
            "options": "Stock Entry",
            "get_query": function () {
                return { filters: { purpose: "Material Transfer", docstatus: 1 } };
            },
        },
        {
            "fieldname": "item_code",
            "label": __("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
        },
        {
            "fieldname": "item_group",
            "label": __("Item Group"),
            "fieldtype": "Link",
            "options": "Item Group",
        },
        {
            "fieldname": "from_warehouse",
            "label": __("From Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
        },
        {
            "fieldname": "to_warehouse",
            "label": __("To Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
        },
    ],
};
