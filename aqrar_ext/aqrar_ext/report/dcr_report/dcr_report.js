// Copyright (c) 2026, Aravind R and contributors
// For license information, please see license.txt

// Summary view: one row per type. Clicking a type opens DCR Detail with the
// same filters, which lists the vouchers behind that figure. The link markup
// is built server-side in dcr_report.py (get_report_link).
frappe.query_reports["DCR Report"] = {
    "filters": [
        {
            "fieldname": "date",
            "label": "Date",
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 0
        },
        {
            "fieldname": "type",
            "label": "Type",
            "fieldtype": "Select",
            "options": [
                "",
                "Opening Cash Balance",
                "Cash Sales",
                "Card/Bank Sales",
                "Credit Sales",
                "Cash Sales Return",
                "Card/Bank Sales Return",
                "Credit Sales Return",
                "Cash Purchases",
                "Card/Bank Purchases",
                "Credit Purchases",
                "Cash Purchase Return",
                "Card/Bank Purchase Return",
                "Credit Purchase Return",
                "Customer Receipts (Cash)",
                "Customer Receipts",
                "Supplier Payments (Cash)",
                "Supplier Payments",
                "Bank Receipts",
                "Bank Payments",
                "Cash Receipts",
                "Cash Payments",
                "Journal Entry",
                "Internal Transfer",
                "Cash Balance"
            ].join("\n"),
            "reqd": 0
        },
        {
            "fieldname": "company",
            "label": "Company",
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company")
        },
        {
            "fieldname": "cost_center",
            "label": "Cost Center",
            "fieldtype": "Link",
            "options": "Cost Center",
            "default": frappe.defaults.get_user_default("Cost Center"),
            "get_query": function() {
                var company = frappe.query_report.get_filter_value("company");
                if (company) {
                    return { "filters": { "company": company } };
                }
                return {};
            }
        },
        {
            "fieldname": "include_draft",
            "label": "Include Draft",
            "fieldtype": "Check",
            "default": 0
        }
    ],

    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (data && data.bold) {
            return `<strong style="font-weight:700;">${value}</strong>`;
        }

        return value;
    }
};
