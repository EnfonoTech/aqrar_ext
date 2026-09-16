// Delivery Note: show the item's valuation rate as soon as item/qty/uom/
// warehouse are set on a row, instead of whatever Item Price ERPNext's own
// price-list lookup would otherwise fill in.
//
// This is purely for immediate feedback in the browser. The real guarantee
// is server-side: aqrar_ext.overrides.delivery_note.set_valuation_rate runs
// on before_validate and re-applies the valuation rate on every save, so a
// stale or overridden client-side value can never actually get saved.

frappe.ui.form.on("Delivery Note Item", {
    item_code: function (frm, cdt, cdn) {
        apply_valuation_rate(frm, cdt, cdn);
    },
    warehouse: function (frm, cdt, cdn) {
        apply_valuation_rate(frm, cdt, cdn);
    },
    qty: function (frm, cdt, cdn) {
        apply_valuation_rate(frm, cdt, cdn);
    },
    uom: function (frm, cdt, cdn) {
        apply_valuation_rate(frm, cdt, cdn);
    },
});

function apply_valuation_rate(frm, cdt, cdn) {
    if (frm.doc.docstatus !== 0) return;

    var row = frappe.get_doc(cdt, cdn);
    if (!row.item_code) return;

    var warehouse = row.warehouse || frm.doc.set_warehouse;
    if (!warehouse) return;

    var item_code = row.item_code;

    // ERPNext's own item_code trigger fetches Item Price / Pricing Rule
    // details asynchronously and fills `rate` with that. Let it finish
    // first, then override with the valuation rate.
    setTimeout(function () {
        var current_row = frappe.get_doc(cdt, cdn);
        if (!current_row || current_row.item_code !== item_code) return;

        frappe.call({
            method: "aqrar_ext.overrides.delivery_note.get_valuation_rate_for_item",
            args: {
                item_code: item_code,
                warehouse: warehouse,
                posting_date: frm.doc.posting_date,
                posting_time: frm.doc.posting_time,
            },
            callback: function (r) {
                if (r.message === undefined || r.message === null) return;

                var latest_row = frappe.get_doc(cdt, cdn);
                if (!latest_row || latest_row.item_code !== item_code) return;

                frappe.model.set_value(cdt, cdn, "price_list_rate", r.message);
                frappe.model.set_value(cdt, cdn, "discount_percentage", 0);
                frappe.model.set_value(cdt, cdn, "discount_amount", 0);
                frappe.model.set_value(cdt, cdn, "rate", r.message);
            },
        });
    }, 500);
}
