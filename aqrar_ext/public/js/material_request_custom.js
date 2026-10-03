// aqrar_ext: Material Request — running counter + close button + urgent

// List view: highlight urgent MRs in red
frappe.listview_settings["Material Request"] = frappe.listview_settings["Material Request"] || {};

frappe.listview_settings["Material Request"].get_indicator = function (doc) {
    if (doc.custom_urgent) {
        return [__("Urgent"), "red", "custom_urgent,=,1"];
    }
};

frappe.listview_settings["Material Request"].onload = function (listview) {
    listview.page.wrapper.on("render-complete", function () {
        listview.$result.find(".list-row-container").each(function () {
            var name = $(this).find(".list-row").attr("data-name");
            if (!name) return;
            var doc = listview.data.find(function (d) { return d.name === name; });
            if (doc && doc.custom_urgent) {
                $(this).css({
                    "background-color": "#fff1f1",
                    "border-left": "3px solid red"
                });
            }
        });
    });
};

frappe.ui.form.on("Material Request", {
    refresh(frm) {
        show_fulfillment(frm);

        if (frm.doc.docstatus === 0) return;

        // Close button (submitted, not closed, not 100% done)
        if (frm.doc.docstatus === 1 && !frm.doc.custom_close_reason
            && frm.doc.per_ordered < 100) {
            frm.add_custom_button(__("Close MR"), function () {
                show_close_dialog(frm);
            }, __("Actions"));
        }

        // Reopen button
        if (frm.doc.docstatus === 1 && frm.doc.custom_close_reason) {
            frm.add_custom_button(__("Reopen MR"), function () {
                frappe.confirm(__("Reopen this Material Request?"), function () {
                    frappe.call({
                        method: "aqrar_ext.events.material_request.reopen_material_request",
                        args: { mr_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Reopening..."),
                        callback: function (r) {
                            if (r.exc) return;
                            frm.reload_doc();
                        },
                    });
                });
            }, __("Actions"));
        }
    },

    // Status is owned by the server endpoints below — setting it here too
    // raced with them and could write "Stopped" onto a reopened request.
});

// Stock balance of source / target warehouse as of the MR transaction date
function set_warehouse_qty(frm, cdt, cdn, warehouse_field, qty_field) {
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
            transaction_date: frm.doc.transaction_date,
        },
        callback: function (r) {
            frappe.model.set_value(cdt, cdn, qty_field, flt(r.message));
        },
    });
}

function refresh_warehouse_qty(frm, cdt, cdn) {
    set_warehouse_qty(frm, cdt, cdn, "from_warehouse", "custom_source_warehouse_qty");
    set_warehouse_qty(frm, cdt, cdn, "warehouse", "custom_target_warehouse_qty");
}

frappe.ui.form.on("Material Request", {
    setup(frm) {
        // Show the per-row warehouses and their qty side by side in the grid
        var grid = frm.get_field("items").grid;
        ["from_warehouse", "custom_source_warehouse_qty", "warehouse", "custom_target_warehouse_qty"]
            .forEach(function (f) { grid.update_docfield_property(f, "in_list_view", 1); });
        ["from_warehouse", "warehouse"].forEach(function (f) {
            grid.update_docfield_property(f, "columns", 2);
        });
        // keep the grid readable: drop the less useful columns
        ["schedule_date"].forEach(function (f) { grid.update_docfield_property(f, "in_list_view", 0); });
    },

    transaction_date(frm) {
        (frm.doc.items || []).forEach(function (row) {
            refresh_warehouse_qty(frm, row.doctype, row.name);
        });
    },
});

frappe.ui.form.on("Material Request Item", {
    item_code(frm, cdt, cdn) {
        // defer so ERPNext's own warehouse defaulting lands first
        setTimeout(function () { refresh_warehouse_qty(frm, cdt, cdn); }, 500);
    },
    from_warehouse(frm, cdt, cdn) {
        set_warehouse_qty(frm, cdt, cdn, "from_warehouse", "custom_source_warehouse_qty");
    },
    warehouse(frm, cdt, cdn) {
        set_warehouse_qty(frm, cdt, cdn, "warehouse", "custom_target_warehouse_qty");
    },
});

function show_fulfillment(frm) {
    $(".aqrar-fulfillment").remove();

    var items = frm.doc.items || [];
    if (!items.length) return;

    var total_req = 0, total_done = 0;
    var rows_html = "";

    items.forEach(function (item) {
        var req = flt(item.stock_qty || item.qty || 0);
        var done = flt(item.ordered_qty || 0);
        var pending = Math.max(req - done, 0);
        total_req += req;
        total_done += done;

        var pct = req > 0 ? Math.round((done / req) * 100) : 0;
        var color = pct >= 100 ? "#16a34a" : pct > 0 ? "#d97706" : "#6b7280";

        rows_html += '<tr>' +
            '<td style="padding:4px 8px;">' + frappe.utils.escape_html(item.item_code || "") + '</td>' +
            '<td style="padding:4px 8px;color:#333;">' + frappe.utils.escape_html(item.item_name || "") + '</td>' +
            '<td style="padding:4px 8px;text-align:center;">' + req + '</td>' +
            '<td style="padding:4px 8px;text-align:center;color:#16a34a;font-weight:600;">' + done + '</td>' +
            '<td style="padding:4px 8px;text-align:center;color:' + (pending > 0 ? "#dc2626" : "#16a34a") + ';font-weight:600;">' + pending + '</td>' +
            '<td style="padding:4px 8px;text-align:center;">' +
                '<span style="color:' + color + ';font-weight:700;">' + pct + '%</span>' +
            '</td>' +
            '</tr>';
    });

    var overall_pct = total_req > 0 ? Math.round((total_done / total_req) * 100) : 0;
    var overall_color = overall_pct >= 100 ? "#16a34a" : overall_pct > 0 ? "#d97706" : "#6b7280";

    var html = '<div class="aqrar-fulfillment" style="padding:10px 15px;background:#f5f7fa;border-radius:6px;margin-bottom:10px;">' +
        '<div style="font-size:13px;font-weight:700;margin-bottom:8px;">' +
            __("Fulfillment") + ': ' +
            '<span style="color:' + overall_color + ';">' + overall_pct + '%</span>' +
            ' <span style="font-weight:400;color:#555;">(' + total_done + ' / ' + total_req + ' ' + __("transferred") + ')</span>' +
        '</div>' +
        '<table style="width:100%;border-collapse:collapse;font-size:12px;">' +
            '<thead><tr style="background:#e5e7eb;">' +
                '<th style="padding:4px 8px;text-align:left;">' + __("Item Code") + '</th>' +
                '<th style="padding:4px 8px;text-align:left;">' + __("Item Name") + '</th>' +
                '<th style="padding:4px 8px;text-align:center;">' + __("Requested") + '</th>' +
                '<th style="padding:4px 8px;text-align:center;">' + __("Transferred") + '</th>' +
                '<th style="padding:4px 8px;text-align:center;">' + __("Pending") + '</th>' +
                '<th style="padding:4px 8px;text-align:center;">' + __("Progress") + '</th>' +
            '</tr></thead>' +
            '<tbody>' + rows_html + '</tbody>' +
        '</table>' +
    '</div>';

    var $ctrl = $(frm.fields_dict.items.wrapper);
    $ctrl.prepend(html);
}

function show_close_dialog(frm) {
    var d = new frappe.ui.Dialog({
        title: __("Close Material Request"),
        fields: [
            {
                fieldtype: "Small Text",
                fieldname: "reason",
                label: __("Reason for Closing"),
                reqd: 1,
            },
        ],
        primary_action_label: __("Close MR"),
        primary_action(values) {
            d.hide();
            frappe.call({
                method: "aqrar_ext.events.material_request.close_material_request",
                args: {
                    mr_name: frm.doc.name,
                    reason: values.reason,
                },
                freeze: true,
                freeze_message: __("Closing..."),
                callback: function (r) {
                    if (r.exc) return;
                    frm.reload_doc();
                },
            });
        },
    });
    d.show();
}
