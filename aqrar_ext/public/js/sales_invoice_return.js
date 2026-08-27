// CR-014: credit notes are entered with positive quantities for usability and
// posted negative. The flip happens in exactly two places — here on validate,
// and server-side in CustomSalesInvoice.fix_return_stock_qty for stock_qty.

frappe.ui.form.on("Sales Invoice", {
    onload(frm) {
        show_return_qty_as_positive(frm);
    },

    refresh(frm) {
        show_return_qty_as_positive(frm);
    },

    validate(frm) {
        if (!frm.doc.is_return) return;
        (frm.doc.items || []).forEach((row) => {
            if (flt(row.qty) > 0) {
                row.qty = -Math.abs(flt(row.qty));
            }
        });
    },
});

function show_return_qty_as_positive(frm) {
    if (!frm.doc.is_return) return;
    // Never rewrite a submitted or cancelled document in memory: the grid would
    // then disagree with the ledger, and any later action would save the flip.
    if (frm.doc.docstatus !== 0) return;

    let changed = false;
    (frm.doc.items || []).forEach((row) => {
        if (flt(row.qty) < 0) {
            row.qty = Math.abs(flt(row.qty));
            changed = true;
        }
    });

    if (changed) frm.refresh_field("items");
}
