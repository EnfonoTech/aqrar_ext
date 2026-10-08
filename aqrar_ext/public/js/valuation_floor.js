// Warn the moment a rate is typed below cost, on Quotation, Sales Order and
// Sales Invoice. The hard block is server-side in
// aqrar_ext/aqrar_ext/utils/valuation_floor.py — this only saves the user from
// finding out at save time.
//
// The floor comes back in COMPANY currency (Bin.valuation_rate is, and so is
// base_net_rate, which the server compares). The row's `rate` is in TRANSACTION
// currency, so it is divided by conversion_rate before comparing and shown in
// the currency the user is actually typing in.

(function () {

const SELLING_ITEM_DOCTYPES = [
    "Quotation Item",
    "Sales Order Item",
    "Sales Invoice Item",
];

function check_valuation_floor(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row || !row.item_code || row.is_free_item) return;
    // A credit note's rate is pinned to the invoice it reverses; the server
    // skips returns for the same reason.
    if (frm.doc.is_return) return;

    frappe.call({
        method: "aqrar_ext.aqrar_ext.utils.valuation_floor.get_valuation_floor",
        args: {
            item_code: row.item_code,
            warehouse: row.warehouse || frm.doc.set_warehouse || "",
            conversion_factor: row.conversion_factor || 1,
            company: frm.doc.company || "",
        },
        callback(r) {
            const floor_company = flt(r.message && r.message.floor);
            if (!floor_company) return;

            const floor = floor_company / (flt(frm.doc.conversion_rate) || 1);
            if (flt(row.rate) >= floor) return;

            frappe.msgprint({
                title: __("Price Below Cost"),
                indicator: "red",
                message: __("Minimum rate for {0} is {1}", [
                    row.item_code,
                    format_currency(floor, frm.doc.currency),
                ]),
            });
        },
    });
}

// "Override Below Cost Price" is shown only to users who were explicitly given the
// Price Override role. Permission levels alone are not enough: Administrator
// implicitly holds every role and would always see it.
let price_override_allowed = null;

function toggle_below_cost_override(frm) {
    const apply = () => frm.toggle_display("custom_override_below_cost", !!price_override_allowed);
    if (price_override_allowed !== null) return apply();
    frappe.call({
        method: "aqrar_ext.aqrar_ext.utils.valuation_floor.has_price_override_role",
        callback(r) {
            price_override_allowed = !!(r && r.message);
            apply();
        },
    });
}

for (const parent_doctype of ["Quotation", "Sales Order", "Sales Invoice"]) {
    frappe.ui.form.on(parent_doctype, { refresh: toggle_below_cost_override });
}

for (const child_doctype of SELLING_ITEM_DOCTYPES) {
    frappe.ui.form.on(child_doctype, { rate: check_valuation_floor });
}

})();
