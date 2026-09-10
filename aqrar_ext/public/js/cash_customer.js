// A cash customer cannot be invoiced on Credit, so do not offer it.
//
// utils/cash_customer.py throws if the mode is Credit, and that stays the
// authority — a Client Script or an import never runs this file. Taking the
// option out of the dropdown just means nobody picks a value that was always
// going to be refused.
//
// Applies to credit notes as well: a return on Credit parks the refund on the
// customer's account instead of handing it back.

(function () {

const MODE_FIELD = "custom_payment_mode";
const CREDIT = "Credit";

function pristine_options(frm) {
    // Captured before anything is stripped, so restoring never resurrects a
    // filtered list. Read from the form's own docfield, not a hardcoded string,
    // so a site that customised the options keeps them.
    if (frm.__aqrar_payment_mode_options === undefined) {
        const df = frm.fields_dict[MODE_FIELD] && frm.fields_dict[MODE_FIELD].df;
        frm.__aqrar_payment_mode_options = (df && df.options) || "";
    }
    return frm.__aqrar_payment_mode_options;
}

function apply_payment_mode_options(frm, is_cash_customer) {
    const all = pristine_options(frm);
    if (!all) return;

    const wanted = is_cash_customer
        ? all.split("\n").filter((o) => o !== CREDIT).join("\n")
        : all;

    const df = frm.fields_dict[MODE_FIELD] && frm.fields_dict[MODE_FIELD].df;
    if (df && df.options !== wanted) {
        frm.set_df_property(MODE_FIELD, "options", wanted);
        frm.refresh_field(MODE_FIELD);
    }

    // Switching to a cash customer with Credit already chosen would otherwise
    // leave a value that is no longer in the list and cannot be saved.
    if (is_cash_customer && frm.doc[MODE_FIELD] === CREDIT) {
        frm.set_value(MODE_FIELD, "");
        frappe.show_alert({
            message: __("{0} is a cash customer — Credit is not available.", [
                frm.doc.customer_name || frm.doc.customer,
            ]),
            indicator: "orange",
        });
    }
}

function sync_payment_modes(frm) {
    if (!frm.fields_dict[MODE_FIELD]) return;

    if (!frm.doc.customer) {
        apply_payment_mode_options(frm, false);
        return;
    }

    frappe.call({
        method: "aqrar_ext.aqrar_ext.utils.cash_customer.get_is_cash_customer",
        args: { customer: frm.doc.customer },
        callback(r) {
            apply_payment_mode_options(frm, !!(r && r.message && r.message.is_cash_customer));
        },
    });
}

frappe.ui.form.on("Sales Invoice", {
    onload: sync_payment_modes,
    refresh: sync_payment_modes,
    customer: sync_payment_modes,
});

})();
