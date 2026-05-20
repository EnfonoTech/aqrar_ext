// aqrar_ext: "Send Statement" button on Customer form
frappe.ui.form.on("Customer", {
    refresh(frm) {
        if (frm.doc.__islocal) return;

        frm.add_custom_button(
            __("Send Statement"),
            function () {
                show_statement_dialog(frm);
            },
            __("View")
        );
    },
});

function show_statement_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: __("Customer Statement"),
        size: "small",
        fields: [
            {
                fieldtype: "Date",
                fieldname: "from_date",
                label: __("From Date"),
                reqd: 1,
                default: frappe.datetime.month_start(),
            },
            {
                fieldtype: "Date",
                fieldname: "to_date",
                label: __("To Date"),
                reqd: 1,
                default: frappe.datetime.month_end(),
            },
        ],
        primary_action_label: __("Download PDF"),
        primary_action(values) {
            const { from_date, to_date } = values;
            if (from_date > to_date) {
                frappe.msgprint(__("From Date cannot be after To Date"));
                return;
            }
            d.hide();
            const url =
                "/api/method/aqrar_ext.aqrar_ext.report.customer_statement.customer_statement.get_pdf" +
                "?customer=" +
                encodeURIComponent(frm.doc.name) +
                "&from_date=" +
                encodeURIComponent(from_date) +
                "&to_date=" +
                encodeURIComponent(to_date);
            window.open(url);
        },
        secondary_action_label: __("View Report"),
        secondary_action() {
            const vals = d.get_values();
            if (!vals) return;
            if (vals.from_date > vals.to_date) {
                frappe.msgprint(__("From Date cannot be after To Date"));
                return;
            }
            d.hide();
            frappe.set_route("query-report", "Customer Statement", {
                customer: frm.doc.name,
                from_date: vals.from_date,
                to_date: vals.to_date,
            });
        },
    });
    d.show();
}
