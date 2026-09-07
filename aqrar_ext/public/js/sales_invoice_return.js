// CR-014: credit notes are entered with positive quantities for usability and
// posted negative. The flip happens in exactly two places — here on validate,
// and server-side in CustomSalesInvoice.fix_return_stock_qty for stock_qty.

frappe.ui.form.on("Sales Invoice", {
    onload(frm) {
        show_return_qty_as_positive(frm);
        patch_return_uom_handler(frm);
    },

    refresh(frm) {
        show_return_qty_as_positive(frm);
        patch_return_uom_handler(frm);
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

// A credit note's rate must follow the invoice it reverses, including when the
// row's UOM is changed. ERPNext's `uom` handler instead re-fetches the price
// list rate and rebuilds the rate as price_list_rate + margin; the margin is an
// absolute amount, so it is never scaled by the conversion factor and the rate
// comes out short. The authoritative correction is server-side in
// aqrar_ext/aqrar_ext/utils/return_rates.py — this keeps the grid honest so the
// user is not shown a rate that save would silently replace.
function patch_return_uom_handler(frm) {
    const cscript = frm.cscript;
    if (!cscript || cscript.aqrar_return_uom_patched) return;

    const core_uom = cscript.uom;

    cscript.uom = function (doc, cdt, cdn) {
        const row = (locals[cdt] || {})[cdn];
        const is_returned_line = doc.is_return && row && row.sales_invoice_item && row.uom;

        if (!is_returned_line) {
            return core_uom ? core_uom.call(this, doc, cdt, cdn) : undefined;
        }

        // Deliberately does NOT delegate: core would fetch the price list rate,
        // which is the value we are replacing.
        return apply_invoiced_rate(this.frm, row);
    };

    cscript.aqrar_return_uom_patched = true;
}

function apply_invoiced_rate(frm, row) {
    return frappe
        .call({
            method: "aqrar_ext.aqrar_ext.utils.return_rates.get_return_rate",
            args: { sales_invoice_item: row.sales_invoice_item, uom: row.uom },
        })
        .then((r) => {
            const invoiced = r && r.message;
            if (!invoiced) return;

            // Written straight onto the row rather than through
            // frappe.model.set_value. set_value runs its triggers through
            // frappe.run_serially, i.e. AFTER this function returns, so the
            // conversion_factor trigger would fire later, call apply_price_list
            // and put the price-list rate straight back. Writing the row and
            // recalculating ourselves keeps it deterministic.
            row.conversion_factor = flt(invoiced.conversion_factor);
            row.price_list_rate = flt(invoiced.price_list_rate);
            // The invoiced margin belongs to the invoiced UOM.
            row.margin_type = "";
            row.margin_rate_or_amount = 0;
            row.rate_with_margin = 0;
            row.rate = flt(invoiced.rate);
            row.stock_qty = flt(row.qty) * flt(row.conversion_factor);
            row.stock_uom_rate = row.conversion_factor
                ? flt(row.rate) / flt(row.conversion_factor)
                : flt(row.rate);

            frm.refresh_field("items");
            frm.dirty();
            return frm.cscript.calculate_taxes_and_totals();
        });
}

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
