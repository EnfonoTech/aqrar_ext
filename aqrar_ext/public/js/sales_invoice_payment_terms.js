frappe.ui.form.on("Sales Invoice", {
    customer: function (frm) {
        if (!frm.doc.customer || frm.doc.ignore_default_payment_terms_template) return;
        frappe.db.get_value("Customer", frm.doc.customer, "payment_terms", function (r) {
            if (r && r.payment_terms) {
                frm.set_value("payment_terms_template", r.payment_terms);
            }
        });
    },
});
