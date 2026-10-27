// Show the item's valuation rate (cost) on each row of Sales/Purchase/Stock transactions.
// Display only: custom_valuation_rate is read-only. Uses the same lookup as the
// below-cost warning (valuation_floor.get_valuation_floor), so the figure shown
// is the figure the floor is enforced against — company currency, per row UOM.

(function () {

const PARENTS = {
    "Sales Invoice": "Sales Invoice Item",
    "Quotation": "Quotation Item",
    "Sales Order": "Sales Order Item",
    "Delivery Note": "Delivery Note Item",
    "Purchase Invoice": "Purchase Invoice Item",
    "Purchase Order": "Purchase Order Item",
    "Purchase Receipt": "Purchase Receipt Item",
    "Stock Entry": "Stock Entry Detail",
};

// Display column only: written quietly (no change event, one cell repainted) and
// asked for through the shared cache, so the below-cost warning's identical
// question costs no second request.
function set_row_valuation_rate(frm, row) {
    if (!row || !row.item_code) return;
    const item_code = row.item_code;

    // Stock Entry receipt row (no source warehouse): stock comes in at the rate
    // typed on the row, not at the warehouse's existing cost.
    if (row.doctype === "Stock Entry Detail" && !row.s_warehouse) {
        aqrar_ext.fd.set_quiet(frm, row.doctype, row.name, "custom_valuation_rate",
            flt(row.basic_rate) * (flt(row.conversion_factor) || 1));
        row.__aqrar_val_done = true;
        return;
    }

    aqrar_ext.fd.get_floor(frm, row).then(function (floor) {
        const current = locals[row.doctype] && locals[row.doctype][row.name];
        if (!current || current.item_code !== item_code) return;
        current.__aqrar_val_done = true;
        aqrar_ext.fd.set_quiet(frm, row.doctype, row.name, "custom_valuation_rate", flt(floor));
    });
}

for (const [parent, child] of Object.entries(PARENTS)) {
    frappe.ui.form.on(parent, {
        refresh(frm) {
            if (frm.doc.docstatus !== 0) return;
            // Only rows never looked up. A row whose cost is genuinely 0 (no stock
            // yet) used to be asked about again on every refresh.
            (frm.doc.items || []).forEach(row => {
                if (row.item_code && !flt(row.custom_valuation_rate) && !row.__aqrar_val_done) {
                    set_row_valuation_rate(frm, row);
                }
            });
        },
    });

    // ERPNext's own item_code trigger fills warehouse / uom / conversion_factor
    // asynchronously; wait for it, then look up the cost for the final row.
    // Each new trigger supersedes the pending one for the same row.
    const timers = {};
    const update = (frm, cdt, cdn) => {
        if (frm.doc.docstatus !== 0) return;
        clearTimeout(timers[cdn]);
        timers[cdn] = setTimeout(() => {
            const row = locals[cdt] && locals[cdt][cdn];
            if (row) {
                row.__aqrar_val_done = false;
                set_row_valuation_rate(frm, row);
            }
        }, 300);
    };
    frappe.ui.form.on(child, {
        item_code: update,
        warehouse: update,
        s_warehouse: update,
        t_warehouse: update,
        uom: update,
        qty: update,
        basic_rate: update,
        conversion_factor: update,
    });
}

})();
