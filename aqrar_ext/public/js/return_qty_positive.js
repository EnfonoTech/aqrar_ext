// CR-014: on a return, each item row gets a Return Qty column where the user
// types the quantity given back, positive. qty stays in the grid and follows as
// its negative, which is what ERPNext posts. The server keeps the two in step
// too (utils/return_qty.flip_return_quantities), so a return saved without this
// script still posts correctly.

(function () {
    const RETURN_QTY = "custom_return_qty";
    const DOCTYPES = {
        "Sales Invoice": "Sales Invoice Item",
        "Delivery Note": "Delivery Note Item",
        "Purchase Invoice": "Purchase Invoice Item",
        "Purchase Receipt": "Purchase Receipt Item",
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

    // Show Return Qty as a grid column on returns only. The field ships with
    // in_list_view = 0, so non-return documents are untouched. On a return, if
    // the extra column would push the grid past its budget, the widest column
    // gives up one unit, so every column that showed before still shows.
    function setup_return_qty_column(frm) {
        const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
        const child_doctype = DOCTYPES[frm.doctype];
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
            const total = listed.reduce((sum, df) => sum + colsize(df), 1);
            const return_df = docfields.find((df) => df.fieldname === RETURN_QTY);
            return_df.in_list_view = 1;

            if (total + colsize(return_df) > GRID_BUDGET) {
                const widest = listed
                    .filter((df) => colsize(df) > 1)
                    .sort((a, b) => colsize(b) - colsize(a))[0];
                if (widest) widest.columns = colsize(widest) - 1;
            }
        }

        grid.reset_grid();
    }

    // A draft return created from the original document (Create > Return)
    // carries negative qty and an empty Return Qty. Fill it in so the column
    // reads correctly from the start. Written straight onto the row: this is
    // display state, and set_value would mark an untouched form dirty.
    function fill_return_qty(frm) {
        if (!frm.doc.is_return || frm.doc.docstatus !== 0) return;
        (frm.doc.items || []).forEach((row) => {
            const expected = Math.abs(flt(row.qty));
            if (flt(row[RETURN_QTY]) !== expected) row[RETURN_QTY] = expected;
        });
    }

    function refresh(frm) {
        fill_return_qty(frm);
        setup_return_qty_column(frm);
    }

    const parent_handlers = {
        onload: fill_return_qty,
        refresh: refresh,
        is_return: refresh,
    };

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
    };

    Object.entries(DOCTYPES).forEach(([doctype, child_doctype]) => {
        frappe.ui.form.on(doctype, parent_handlers);
        frappe.ui.form.on(child_doctype, child_handlers);
    });
})();
