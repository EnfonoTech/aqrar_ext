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
                        callback: function () { frm.reload_doc(); },
                    });
                });
            }, __("Actions"));
        }
    },

    before_save(frm) {
        if (frm.doc.custom_close_reason && frm.doc.docstatus === 1) {
            frm.set_value("status", "Stopped");
        }
    },
});

function show_fulfillment(frm) {
    // Remove previous
    $(".aqrar-fulfillment").remove();

    var total_req = 0, total_done = 0;
    (frm.doc.items || []).forEach(function (item) {
        total_req += flt(item.stock_qty || item.qty || 0);
        total_done += flt(item.ordered_qty || 0);
    });

    var pct = total_req > 0 ? Math.round((total_done / total_req) * 100) : 0;
    var color = pct >= 100 ? "green" : pct > 0 ? "orange" : "gray";
    var bar = "";
    for (var i = 0; i < 10; i++) bar += i < Math.round(pct / 10) ? "█" : "░";

    var html = '<div class="aqrar-fulfillment" style="padding:10px 15px;background:#f5f7fa;' +
        'border-radius:6px;margin-bottom:10px;font-size:13px;">' +
        '<strong>' + __("Fulfillment") + ':</strong> ' +
        '<span style="color:' + (pct >= 100 ? '#16a34a' : pct > 0 ? '#d97706' : '#6b7280') + ';font-weight:bold;">' +
        pct + '%</span> ' +
        '(' + total_done + ' / ' + total_req + ' ' + __("transferred") + ') ' +
        '<span style="font-family:monospace;">' + bar + '</span></div>';

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
                callback: function () { frm.reload_doc(); },
            });
        },
    });
    d.show();
}
