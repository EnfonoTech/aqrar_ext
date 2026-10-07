// "Back-date Stock" on a submitted Purchase Invoice with Update Stock: move the
// stock-in of chosen items to an earlier date without cancelling the invoice.
// Supplier payable and taxes stay on the invoice date. Server side:
// utils/backdate_stock.py.

(function () {
    const METHOD = "aqrar_ext.aqrar_ext.utils.backdate_stock.";

    // Enabled and roles are set in Stock Reposting Settings.
    function can_backdate(frm) {
        return frm.doc.docstatus === 1 && frm.doc.update_stock && !frm.doc.is_return;
    }

    function open_dialog(frm) {
        frappe.call({ method: METHOD + "get_stock_items", args: { purchase_invoice: frm.doc.name } }).then((r) => {
            const rows = (r.message || []).map((row) => ({
                item_code: row.item_code,
                item_name: row.item_name,
                warehouse: row.warehouse,
                qty: row.qty + " " + (row.stock_uom || ""),
                stock_date: frappe.datetime.str_to_user(row.posting_date) + " " + row.posting_time.slice(0, 5),
            }));
            if (!rows.length) {
                frappe.msgprint(__("This invoice has no stock entries."));
                return;
            }

            const d = new frappe.ui.Dialog({
                title: __("Back-date Stock"),
                size: "large",
                fields: [
                    {
                        fieldtype: "HTML",
                        options:
                            '<p class="text-muted">' +
                            __("Tick (checkbox on the left) the items whose stock really came in earlier and pick that date. Their stock and its Stock In Hand value move to that date; the supplier payable and taxes stay on the invoice date.") +
                            "</p>",
                    },
                    { fieldname: "new_date", fieldtype: "Date", label: __("New Stock Date"), reqd: 1 },
                    { fieldtype: "Column Break" },
                    { fieldname: "new_time", fieldtype: "Time", label: __("New Stock Time"), reqd: 1, default: "09:00:00" },
                    { fieldtype: "Section Break" },
                    {
                        fieldname: "items",
                        fieldtype: "Table",
                        label: __("Items"),
                        cannot_add_rows: true,
                        cannot_delete_rows: true,
                        in_place_edit: true,
                        data: rows,
                        fields: [
                            { fieldname: "item_code", fieldtype: "Data", label: __("Item Code"), in_list_view: 1, read_only: 1, columns: 2 },
                            { fieldname: "item_name", fieldtype: "Data", label: __("Item Name"), in_list_view: 1, read_only: 1, columns: 4 },
                            { fieldname: "qty", fieldtype: "Data", label: __("Qty"), in_list_view: 1, read_only: 1, columns: 1 },
                            { fieldname: "stock_date", fieldtype: "Data", label: __("Current Stock Date"), in_list_view: 1, read_only: 1, columns: 2 },
                            { fieldname: "warehouse", fieldtype: "Data", label: __("Warehouse"), read_only: 1 },
                        ],
                    },
                ],
                primary_action_label: __("Back-date"),
                primary_action(values) {
                    // The rows ticked with the grid's own row checkbox.
                    const selected = d.fields_dict.items.grid.get_selected_children();
                    const items = [...new Set(selected.map((row) => row.item_code))];
                    if (!items.length) {
                        frappe.msgprint(__("Tick at least one item."));
                        return;
                    }
                    frappe.confirm(
                        __("Move the stock-in of {0} to {1} {2}?", [
                            items.join(", "),
                            frappe.datetime.str_to_user(values.new_date),
                            values.new_time,
                        ]),
                        () => {
                            frappe
                                .call({
                                    method: METHOD + "backdate_stock_in",
                                    args: {
                                        purchase_invoice: frm.doc.name,
                                        item_codes: items,
                                        new_date: values.new_date,
                                        new_time: values.new_time,
                                    },
                                    freeze: true,
                                    freeze_message: __("Back-dating stock..."),
                                })
                                .then((res) => {
                                    d.hide();
                                    frappe.msgprint({
                                        title: __("Stock back-dated"),
                                        indicator: "green",
                                        message: __("Stock-in moved for {0}. Stock valuation is being reposted ({1}); check Repost Item Valuation for status.", [
                                            res.message.items.join(", "),
                                            res.message.reposts.join(", "),
                                        ]),
                                    });
                                    frm.reload_doc();
                                });
                        }
                    );
                },
            });
            d.show();
        });
    }

    frappe.ui.form.on("Purchase Invoice", {
        refresh(frm) {
            if (!can_backdate(frm)) return;
            frappe.call({ method: METHOD + "get_settings" }).then((r) => {
                if (!(r.message && r.message.allowed)) return;
                frm.add_custom_button(__("Back-date Stock"), () => open_dialog(frm), __("Stock"));
            });
        },
    });
})();
