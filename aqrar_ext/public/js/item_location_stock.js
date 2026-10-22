// "Stock" button on each row of the item table of every sales and purchase
// document: opens a popup with the row item's quantity in every warehouse of the
// document's company.

(function () {
    const CHILD_DOCTYPES = [
        "Sales Invoice Item",
        "Quotation Item",
        "Sales Order Item",
        "Delivery Note Item",
        "Purchase Invoice Item",
        "Purchase Order Item",
        "Purchase Receipt Item",
    ];

    function show_stock(frm, row) {
        frappe.call({
            method: "aqrar_ext.api.item_insights.get_item_warehouse_stock",
            args: { item_code: row.item_code, company: frm.doc.company, limit: 100 },
            callback(r) {
                const rows = r.message || [];
                const esc = frappe.utils.escape_html;
                const body = rows.length
                    ? rows
                          .map(
                              (d) =>
                                  `<tr><td>${esc(d.warehouse)}</td>` +
                                  `<td class="text-right">${format_number(d.actual_qty, null, 3)}</td></tr>`
                          )
                          .join("")
                    : `<tr><td colspan="2" class="text-muted">${__("No stock in any warehouse of this company.")}</td></tr>`;
                const total = rows.reduce((t, d) => t + flt(d.actual_qty), 0);
                const dlg = new frappe.ui.Dialog({
                    title: __("Stock: {0}", [row.item_code]),
                    fields: [{ fieldtype: "HTML", fieldname: "stock" }],
                });
                dlg.fields_dict.stock.$wrapper.html(
                    `<p class="text-muted">${esc(frm.doc.company)}</p>` +
                        `<table class="table table-bordered"><thead><tr><th>${__("Warehouse")}</th>` +
                        `<th class="text-right">${__("Qty")}</th></tr></thead><tbody>${body}</tbody>` +
                        (rows.length
                            ? `<tfoot><tr><th>${__("Total")}</th><th class="text-right">${format_number(total, null, 3)}</th></tr></tfoot>`
                            : "") +
                        `</table>`
                );
                dlg.show();
            },
        });
    }

    CHILD_DOCTYPES.forEach((child) => {
        frappe.ui.form.on(child, {
            custom_view_stock(frm, cdt, cdn) {
                const row = locals[cdt][cdn];
                if (!row.item_code) {
                    frappe.msgprint(__("Select an item first."));
                    return;
                }
                if (!frm.doc.company) {
                    frappe.msgprint(__("Select a company first."));
                    return;
                }
                show_stock(frm, row);
            },
        });
    });
})();
