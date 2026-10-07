// CR-014: on a return, each item row gets three columns next to qty, all in the
// row's UOM and restated whenever the UOM changes:
//   Total Qty (read-only)    - what the original row carried (5 Box, or 50 Nos)
//   Returned Qty (read-only) - already returned against it by earlier returns
//   Return Qty               - where the user types the quantity given back,
//                              positive
// qty stays in the grid and follows as the negative of Return Qty, which is what
// ERPNext posts. The server keeps all of them in step too
// (utils/return_qty.flip_return_quantities), so a return saved without this
// script still posts correctly.

(function () {
    const RETURN_QTY = "custom_return_qty";
    const TOTAL_QTY = "custom_total_qty";
    const RETURNED_QTY = "custom_returned_qty";
    const EXTRA_COLUMNS = [TOTAL_QTY, RETURNED_QTY, RETURN_QTY];
    // doctype -> [its item doctype, the field on a return row naming the
    // original row]. Mirrors RETURN_REFERENCE in utils/return_rates.py.
    const DOCTYPES = {
        "Sales Invoice": ["Sales Invoice Item", "sales_invoice_item"],
        "Delivery Note": ["Delivery Note Item", "dn_detail"],
        "Purchase Invoice": ["Purchase Invoice Item", "purchase_invoice_item"],
        "Purchase Receipt": ["Purchase Receipt Item", "purchase_receipt_item"],
        "POS Invoice": ["POS Invoice Item", "pos_invoice_item"],
    };
    // Frappe's grid fits columns into a width budget of 11 (the row number
    // takes 1) and silently drops whatever does not fit.
    const GRID_BUDGET = 11;

    function colsize(df) {
        if (df.columns) return df.columns;
        if (df.fieldtype === "Small Text") return 3;
        if (df.fieldtype === "Check") return 1;
        return 2;
    }

    // Show the extra columns on returns only. The fields ship with
    // in_list_view = 0, so non-return documents are untouched. On a return, if
    // the extra columns would push the grid past its budget, the widest columns
    // give up a unit each until they fit, so every column that showed before
    // still shows.
    function setup_return_columns(frm) {
        const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
        const child_doctype = DOCTYPES[frm.doctype][0];
        if (!grid || !frappe.meta.has_field(child_doctype, RETURN_QTY)) return;

        // Per-document docfield copies, which the grid re-reads on every
        // refresh. Reset them to the doctype's own definition first, so this is
        // idempotent and undoes itself when Is Return is unticked.
        const docfields = frappe.meta.get_docfields(child_doctype, frm.docname);
        const original = {};
        frappe.get_meta(child_doctype).fields.forEach((df) => (original[df.fieldname] = df));
        docfields.forEach((df) => {
            const meta_df = original[df.fieldname];
            if (!meta_df) return;
            df.in_list_view = meta_df.in_list_view;
            df.columns = meta_df.columns;
        });

        if (frm.doc.is_return) {
            const listed = docfields.filter(
                (df) => df.in_list_view && !df.hidden && !frappe.model.layout_fields.includes(df.fieldtype)
            );
            let total = listed.reduce((sum, df) => sum + colsize(df), 1);

            docfields
                .filter((df) => EXTRA_COLUMNS.includes(df.fieldname))
                .forEach((df) => {
                    df.in_list_view = 1;
                    total += colsize(df);
                });

            while (total > GRID_BUDGET) {
                const widest = listed
                    .filter((df) => colsize(df) > 1)
                    .sort((a, b) => colsize(b) - colsize(a))[0];
                if (!widest) break;
                widest.columns = colsize(widest) - 1;
                total -= 1;
            }
        }

        grid.reset_grid();
    }

    // Create > Return pre-fills every row with the whole returnable quantity.
    // Users are meant to type what actually comes back into Return Qty, so a
    // freshly mapped return starts every row at zero instead; rows still at
    // zero on save are dropped server-side (utils/return_qty.py). A return
    // that has been saved already keeps its quantities.
    const QTY_FIELDS = ["qty", "stock_qty", "received_qty", "received_stock_qty"];

    function clear_mapped_quantities(frm) {
        // Flagged on the doc, not the form: Frappe reuses one form object for
        // every document of a doctype, so a form-level flag set by the first
        // return would skip every return opened after it. Double-underscore
        // fields are never saved.
        if (!frm.is_new() || !frm.doc.return_against || frm.doc.__aqrar_quantities_cleared) return;
        frm.doc.__aqrar_quantities_cleared = 1;
        (frm.doc.items || []).forEach((row) => {
            QTY_FIELDS.forEach((fieldname) => {
                if (fieldname in row) row[fieldname] = 0;
            });
            row[RETURN_QTY] = 0;
        });
        frm.cscript.calculate_taxes_and_totals && frm.cscript.calculate_taxes_and_totals();
    }

    // Fill Total / Returned Qty (and Return Qty, from qty) on a draft return so
    // the columns read correctly from the start. Written straight onto the
    // rows: this is display state, and set_value would mark an untouched form
    // dirty.
    function fill_return_columns(frm) {
        if (!frm.doc.is_return || frm.doc.docstatus !== 0) return;
        clear_mapped_quantities(frm);
        (frm.doc.items || []).forEach((row) => {
            row[RETURN_QTY] = Math.abs(flt(row.qty));
        });
        return load_original_stock_qty(frm).then(() => {
            (frm.doc.items || []).forEach((row) => set_original_columns(frm, row));
            frm.refresh_field("items");
        });
    }

    // The original rows' stock_qty and already-returned stock_qty, cached on
    // the form. Stock units are UOM-independent, so dividing by a row's
    // conversion factor gives both in whatever UOM that row is in now.
    function load_original_stock_qty(frm) {
        const reference_field = DOCTYPES[frm.doctype][1];
        const names = (frm.doc.items || []).map((row) => row[reference_field]).filter(Boolean);
        if (!frm.doc.return_against || !names.length) {
            frm.aqrar_original_stock_qty = {};
            return Promise.resolve();
        }
        return frappe
            .call({
                method: "aqrar_ext.aqrar_ext.utils.return_qty.get_original_stock_qty",
                args: {
                    doctype: frm.doctype,
                    return_against: frm.doc.return_against,
                    names,
                    exclude: frm.is_new() ? null : frm.doc.name,
                },
            })
            .then((r) => {
                frm.aqrar_original_stock_qty = (r && r.message) || {};
            });
    }

    function set_original_columns(frm, row) {
        const [total, returned] =
            (frm.aqrar_original_stock_qty || {})[row[DOCTYPES[frm.doctype][1]]] || [0, 0];
        const factor = flt(row.conversion_factor) || 1;
        row[TOTAL_QTY] = flt(total) / factor;
        row[RETURNED_QTY] = flt(returned) / factor;
    }

    // Editing qty on a row ERPNext does not see as "mapped" re-fetches the price
    // list rate and rebuilds the rate from it plus the row's old margin. ERPNext's
    // list (transaction.js is_a_mapped_document) knows the return reference of
    // Sales Invoice, Delivery Note and Purchase Receipt rows but not of Purchase
    // Invoice or POS Invoice rows, so typing a Return Qty there turned an invoiced
    // 300 into 500. A return row carrying its original row's reference is mapped:
    // it keeps the invoiced rate.
    function patch_mapped_check(frm) {
        const cscript = frm.cscript;
        if (!cscript || !cscript.is_a_mapped_document || cscript.aqrar_return_mapped_patched) return;
        const core = cscript.is_a_mapped_document;
        const reference_field = DOCTYPES[frm.doctype][1];
        cscript.is_a_mapped_document = function (item) {
            if (item && this.frm.doc.is_return && item[reference_field]) return true;
            return core.call(this, item);
        };
        cscript.aqrar_return_mapped_patched = true;
    }

    const parent_handlers = {
        onload(frm) {
            patch_mapped_check(frm);
            return fill_return_columns(frm);
        },
        refresh(frm) {
            patch_mapped_check(frm);
            setup_return_columns(frm);
        },
        is_return(frm) {
            fill_return_columns(frm);
            setup_return_columns(frm);
        },
    };

    // A changed UOM changes the conversion factor, and with it Total and
    // Returned Qty. Return Qty and qty keep their number, now read in the new
    // UOM; ERPNext's conversion_factor handler (or, on a credit note, the
    // invoiced-rate UOM patch) recomputes stock_qty. The conversion factor
    // arrives asynchronously, so wait for those calls first. The credit-note
    // patch in sales_invoice_return.js writes the factor directly, without a
    // conversion_factor event, so it fires aqrar_return_uom_applied instead.
    function after_uom_change(frm, cdt, cdn) {
        if (!frm.doc.is_return) return;
        frappe.after_ajax(() => {
            const row = locals[cdt][cdn];
            if (!row) return;
            set_original_columns(frm, row);
            frm.refresh_field("items");
        });
    }

    const child_handlers = {
        [RETURN_QTY](frm, cdt, cdn) {
            const row = locals[cdt][cdn];
            if (!frm.doc.is_return) return;
            const qty = -Math.abs(flt(row[RETURN_QTY]));
            // Through set_value, so ERPNext's own qty handler recomputes
            // stock_qty, amount and (on purchase rows) received_qty.
            if (flt(row.qty) !== qty) frappe.model.set_value(cdt, cdn, "qty", qty);
        },
        qty(frm, cdt, cdn) {
            const row = locals[cdt][cdn];
            if (!frm.doc.is_return) return;
            const return_qty = Math.abs(flt(row.qty));
            if (flt(row[RETURN_QTY]) !== return_qty) {
                frappe.model.set_value(cdt, cdn, RETURN_QTY, return_qty);
            }
        },
        uom: after_uom_change,
        conversion_factor: after_uom_change,
        aqrar_return_uom_applied: after_uom_change,
    };

    Object.entries(DOCTYPES).forEach(([doctype, [child_doctype]]) => {
        frappe.ui.form.on(doctype, parent_handlers);
        frappe.ui.form.on(child_doctype, child_handlers);
    });
})();
