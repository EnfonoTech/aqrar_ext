// CR-023: one-click "Book Commission" on a submitted Sales Invoice, showing
// whether a commission Journal Entry already exists.

frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (frm.is_new() || frm.doc.docstatus !== 1) return;

        frappe.call({
            method: "aqrar_ext.api.commission.get_commission_je_status",
            args: { sales_invoice: frm.doc.name },
            callback: function (r) {
                if (r.exc) return;
                const status = r.message || {};

                if (status.exists) {
                    frm.add_custom_button(
                        __("Commission JE ({0})", [status.status]),
                        function () {
                            frappe.set_route("Form", "Journal Entry", status.name);
                        },
                        __("View")
                    );
                    return;
                }

                frm.add_custom_button(
                    __("Book Commission"),
                    function () {
                        frappe._aqrar_commission_si = frm.doc.name;
                        frappe.new_doc("Journal Entry");
                    },
                    __("Create")
                );
            },
        });
    },
});
