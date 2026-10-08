// aqrar_ext: Stock Entry — qty of the chosen item in the source / target
// warehouse as of the posting date.

function se_set_qty(frm, cdt, cdn, warehouse_field, qty_field) {
    var row = locals[cdt][cdn];
    if (!row.item_code || !row[warehouse_field]) {
        frappe.model.set_value(cdt, cdn, qty_field, 0);
        return;
    }
    frappe.call({
        method: "aqrar_ext.events.material_request.get_warehouse_qty",
        args: {
            item_code: row.item_code,
            warehouse: row[warehouse_field],
            transaction_date: frm.doc.posting_date,
        },
        callback: function (r) {
            frappe.model.set_value(cdt, cdn, qty_field, flt(r.message));
        },
    });
}

function se_refresh_row(frm, cdt, cdn) {
    se_set_qty(frm, cdt, cdn, "s_warehouse", "custom_source_warehouse_qty");
    se_set_qty(frm, cdt, cdn, "t_warehouse", "custom_target_warehouse_qty");
}

frappe.ui.form.on("Stock Entry", {
    // Rows mapped from a Material Request never fire item_code, so fill the
    // quantities as soon as the draft opens (before it is first saved).
    refresh(frm) {
        if (frm.doc.docstatus !== 0) return;
        (frm.doc.items || []).forEach(function (row) {
            if (row.item_code && ((row.s_warehouse && row.custom_source_warehouse_qty == null)
                || (row.t_warehouse && row.custom_target_warehouse_qty == null)
                || (!flt(row.custom_source_warehouse_qty) && !flt(row.custom_target_warehouse_qty)))) {
                se_refresh_row(frm, row.doctype, row.name);
            }
        });
    },
    posting_date(frm) {
        (frm.doc.items || []).forEach(function (row) {
            se_refresh_row(frm, row.doctype, row.name);
        });
    },
});

frappe.ui.form.on("Stock Entry Detail", {
    item_code(frm, cdt, cdn) {
        // defer so ERPNext's own warehouse defaulting lands first
        setTimeout(function () { se_refresh_row(frm, cdt, cdn); }, 500);
    },
    s_warehouse(frm, cdt, cdn) {
        se_set_qty(frm, cdt, cdn, "s_warehouse", "custom_source_warehouse_qty");
    },
    t_warehouse(frm, cdt, cdn) {
        se_set_qty(frm, cdt, cdn, "t_warehouse", "custom_target_warehouse_qty");
    },
});
