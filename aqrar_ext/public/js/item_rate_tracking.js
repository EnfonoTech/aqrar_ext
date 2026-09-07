// Wrapped in an IIFE for the same reason as price_assist.js: app_include_js
// shares one global lexical scope.
(function () {
// Actual rate + per-row discount-on-amount tracking.
//
// Ported from fateh_trading (`ram` branch), which shipped this as seven
// byte-identical files — sales_invoice.js, delivery_note.js, sales_order.js,
// quotation.js, purchase_invoice.js, purchase_order.js, purchase_receipt.js —
// differing only in the doctype name. One config-driven registration replaces
// all seven.
//
// The weighted-discount handler those files carried is deliberately absent:
// that feature was not ported, so `custom_weighted_discount` and
// `custom_item_discount` do not exist here.
//
// custom_actual_rate  — the rate before any discount-on-amount is applied.
// custom_discount_on_amount — a total discount for the row, spread over its qty.

const RATE_TRACKING_DOCTYPES = [
    "Sales Invoice Item",
    "Delivery Note Item",
    "Sales Order Item",
    "Quotation Item",
    "Purchase Invoice Item",
    "Purchase Order Item",
    "Purchase Receipt Item",
];

for (const child_doctype of RATE_TRACKING_DOCTYPES) {

    frappe.ui.form.on(child_doctype, {

        rate(frm, cdt, cdn) {
            const row = locals[cdt][cdn];

            // Our own write below re-enters this handler; without the flag the
            // discounted rate would be stored back as the actual rate.
            if (row.__updating_rate_programmatically) return;

            frappe.model.set_value(cdt, cdn, "custom_actual_rate", row.rate);
            frappe.model.set_value(cdt, cdn, "custom_discount_on_amount", null);
        },

        item_code(frm, cdt, cdn) {
            const row = locals[cdt][cdn];
            if (row.price_list_rate) {
                frappe.model.set_value(cdt, cdn, "custom_actual_rate", row.price_list_rate);
            }
        },

        custom_discount_on_amount(frm, cdt, cdn) {
            const row = locals[cdt][cdn];
            if (!row.custom_discount_on_amount) return;

            const discount_per_unit = row.custom_discount_on_amount / row.qty;
            const new_rate = row.custom_actual_rate - discount_per_unit;

            row.__updating_rate_programmatically = true;
            frappe.model.set_value(cdt, cdn, "rate", new_rate);
            setTimeout(() => { delete row.__updating_rate_programmatically; }, 100);
        }
    });
}

})();
