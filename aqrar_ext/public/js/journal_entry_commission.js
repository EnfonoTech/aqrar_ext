// CR-023: a commission / discount Journal Entry raised from a Sales Invoice
// carries a link back to that invoice and pre-fills the company's configured
// commission accounts.

frappe.ui.form.on("Journal Entry", {
    onload: function (frm) {
        if (!frm.is_new()) return;

        const source_invoice = frappe._aqrar_commission_si;
        if (!source_invoice) return;
        delete frappe._aqrar_commission_si;

        frappe.call({
            method: "aqrar_ext.api.commission.get_commission_defaults",
            args: { sales_invoice: source_invoice },
            callback: function (r) {
                if (r.exc || !r.message) return;
                apply_commission_defaults(frm, r.message);
            },
        });
    },
});

function apply_commission_defaults(frm, defaults) {
    frm.set_value("company", defaults.company);
    if (defaults.posting_date) frm.set_value("posting_date", defaults.posting_date);
    frm.set_value("voucher_type", "Journal Entry");

    // The link field only exists once setup_data has provisioned it.
    if (defaults.reference_field) {
        frm.set_value(defaults.reference_field, defaults.sales_invoice);
    } else {
        frappe.msgprint({
            title: __("Reference Field Missing"),
            message: __(
                "The Journal Entry reference-invoice field is not installed. Run bench migrate so commission entries can be traced back to their invoice."
            ),
            indicator: "orange",
        });
    }

    frm.clear_table("accounts");

    // Debit: commission expense. Credit: commission payable.
    // Party/Reference used to be pre-filled as Customer/this invoice on the
    // credit row, but the commission_payable account isn't configured as a
    // Receivable/Payable account for the Customer party type — ERPNext's own
    // party-type-vs-account validation rejected that on submit. Account
    // stays pre-filled; Party is left for the user to fill in.
    const expense_account = defaults.accounts.commission_expense;
    if (expense_account) {
        const debit_row = frm.add_child("accounts");
        debit_row.account = expense_account;
        debit_row.cost_center = defaults.cost_center;
    }

    const credit_row = frm.add_child("accounts");
    credit_row.cost_center = defaults.cost_center;
    if (defaults.accounts.commission_payable) {
        credit_row.account = defaults.accounts.commission_payable;
    }

    frm.refresh_field("accounts");

    if (!expense_account || !defaults.accounts.commission_payable) {
        frappe.show_alert(
            {
                message: __("Set the default commission accounts on {0} to pre-fill these rows.", [
                    defaults.company,
                ]),
                indicator: "orange",
            },
            7
        );
    }
}
