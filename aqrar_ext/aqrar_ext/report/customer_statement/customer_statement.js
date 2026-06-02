frappe.query_reports["Customer Statement"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            reqd: 1,
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "Link",
            options: "Customer",
            reqd: 1,
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.month_start(),
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.month_end(),
        },
        {
            fieldname: "ageing_based_on",
            label: __("Ageing Based On"),
            fieldtype: "Select",
            options: ["Posting Date", "Due Date"],
            default: "Posting Date",
        },
    ],
};
