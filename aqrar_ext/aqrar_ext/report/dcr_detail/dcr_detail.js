// Copyright (c) 2026, Aravind R and contributors
// For license information, please see license.txt

// Drill-down for DCR Report. Normally reached by clicking a type in the
// summary, which fills these filters from the URL.
frappe.query_reports["DCR Detail"] = {
    "filters": [
        {
            "fieldname": "report_type",
            "label": "Type",
            "fieldtype": "Select",
            "options": [
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
            "default": "Cash Sales",
            "reqd": 1
        },
        {
            "fieldname": "date",
            "label": "Date",
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
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
            "get_query": function() {
                var company = frappe.query_report.get_filter_value("company");
                if (company) {
                    return { "filters": { "company": company } };
                }
                return {};
            }
        }
    ]
};
