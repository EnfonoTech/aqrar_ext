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

function set_row_valuation_rate(frm, row) {
    if (!row || !row.item_code) return;
    const item_code = row.item_code;

    frappe.call({
        method: "aqrar_ext.aqrar_ext.utils.valuation_floor.get_valuation_floor",
        args: {
            item_code: item_code,
            warehouse: row.warehouse || row.s_warehouse || row.t_warehouse || frm.doc.set_warehouse || "",
            conversion_factor: row.conversion_factor || 1,
            company: frm.doc.company || "",
        },
        callback(r) {
            if (r.exc || !r.message) return;
            const current = locals[row.doctype] && locals[row.doctype][row.name];
            if (!current || current.item_code !== item_code) return;
            frappe.model.set_value(row.doctype, row.name, "custom_valuation_rate", flt(r.message.floor));
        },
    });
}

for (const [parent, child] of Object.entries(PARENTS)) {
    frappe.ui.form.on(parent, {
        refresh(frm) {
            if (frm.doc.docstatus !== 0) return;
            (frm.doc.items || []).forEach(row => {
                if (row.item_code && !flt(row.custom_valuation_rate)) set_row_valuation_rate(frm, row);
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
            if (row) set_row_valuation_rate(frm, row);
        }, 300);
    };
    frappe.ui.form.on(child, {
        item_code: update,
        warehouse: update,
        s_warehouse: update,
        t_warehouse: update,
        uom: update,
        conversion_factor: update,
    });
}

})();
