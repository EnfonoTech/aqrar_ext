frappe.ui.form.on('Item', {

    refresh: function(frm) {
        if (!frm.doc.__islocal) {
            check_uom_lock(frm);
        }
    },

    onload: function(frm) {
        if (!frm.doc.__islocal) {
            check_uom_lock(frm);
        }
    },

    item_group: function(frm) {
        // Different Item Groups often follow different item_code numbering —
        // show what's already in the group so staff can match the pattern
        // instead of guessing the next code.
        if (!frm.is_new() || !frm.doc.item_group) return;
        show_item_code_history(frm.doc.item_group);
    },

});

// The New Item "Quick Entry" popup (opened from the Item list's + button) is
// a plain frappe.ui.Dialog, not a full form — frappe.ui.form.on() triggers
// above never fire inside it. Patch the dialog itself so item_group there
// gets the same history popup, and add the Item Code Lookup link too.
(function () {
    if (frappe.ui.form.QuickEntryForm.prototype._aqrar_item_group_history_patched) return;

    var core_render_dialog = frappe.ui.form.QuickEntryForm.prototype.render_dialog;
    frappe.ui.form.QuickEntryForm.prototype.render_dialog = function () {
        core_render_dialog.apply(this, arguments);

        if (this.doctype !== "Item") return;

        var field = this.dialog.fields_dict.item_group;
        if (field) {
            var core_onchange = field.df.onchange;
            field.df.onchange = function () {
                if (core_onchange) core_onchange.apply(this, arguments);
                var item_group = field.get_value();
                if (item_group) show_item_code_history(item_group);
            };
        }

        $('<div style="text-align:right; margin-bottom:10px;">' +
            '<a href="#" class="aqrar-item-code-lookup-link">' + __("Item Code Lookup") + '</a>' +
          '</div>')
            .prependTo(this.dialog.$wrapper.find(".modal-body"))
            .find(".aqrar-item-code-lookup-link")
            .on("click", function (e) {
                e.preventDefault();
                open_item_code_lookup();
            });
    };

    frappe.ui.form.QuickEntryForm.prototype._aqrar_item_group_history_patched = true;
})();

// List view toolbar button — same lookup, reachable without opening New Item.
frappe.listview_settings = frappe.listview_settings || {};
frappe.listview_settings["Item"] = Object.assign({}, frappe.listview_settings["Item"], {
    onload: function (listview) {
        var core_onload = (frappe.listview_settings["Item"] || {}).onload;
        if (core_onload) core_onload(listview);
        listview.page.add_inner_button(__("Item Code Lookup"), function () {
            open_item_code_lookup();
        });
    },
});

function open_item_code_lookup() {
    var dialog = new frappe.ui.Dialog({
        title: __("Item Code Lookup"),
        fields: [
            {
                fieldtype: "Link",
                fieldname: "item_group",
                label: __("Item Group"),
                options: "Item Group",
                onchange: run_lookup_search,
            },
            {
                fieldtype: "Data",
                fieldname: "item_code_txt",
                label: __("Item Code contains"),
                onchange: run_lookup_search,
            },
            { fieldtype: "HTML", fieldname: "results_area" },
        ],
    });

    var search_timeout;
    function run_lookup_search() {
        clearTimeout(search_timeout);
        search_timeout = setTimeout(function () {
            var item_group = dialog.get_value("item_group");
            var item_code_txt = dialog.get_value("item_code_txt");
            var $wrapper = dialog.fields_dict.results_area.$wrapper;

            if (!item_group && !item_code_txt) {
                $wrapper.html('<p class="text-muted">' + __("Enter an Item Group or Item Code to search.") + "</p>");
                return;
            }

            var filters = {};
            if (item_group) filters.item_group = item_group;
            if (item_code_txt) filters.item_code = ["like", "%" + item_code_txt + "%"];

            frappe.call({
                method: "frappe.client.get_list",
                args: {
                    doctype: "Item",
                    filters: filters,
                    fields: ["item_code", "item_name", "item_group"],
                    order_by: "item_code asc",
                    limit_page_length: 20,
                },
                callback: function (r) {
                    var rows = r.message || [];
                    if (!rows.length) {
                        $wrapper.html('<p class="text-muted">' + __("No matching items.") + "</p>");
                        return;
                    }

                    var html = '<div style="max-height:350px; overflow-y:auto;">' +
                        '<table class="table table-bordered">' +
                            '<thead><tr>' +
                                '<th>' + __("Item Code") + '</th>' +
                                '<th>' + __("Item Name") + '</th>' +
                                '<th>' + __("Item Group") + '</th>' +
                            '</tr></thead>' +
                            '<tbody>';

                    rows.forEach(function (row) {
                        html +=
                            '<tr>' +
                                '<td>' + frappe.utils.escape_html(row.item_code) + '</td>' +
                                '<td>' + frappe.utils.escape_html(row.item_name || "") + '</td>' +
                                '<td>' + frappe.utils.escape_html(row.item_group || "") + '</td>' +
                            '</tr>';
                    });

                    html += '</tbody></table></div>';
                    $wrapper.html(html);
                },
            });
        }, 300);
    }

    dialog.show();
    dialog.fields_dict.results_area.$wrapper.html(
        '<p class="text-muted">' + __("Enter an Item Group or Item Code to search.") + "</p>"
    );
}

function show_item_code_history(item_group) {
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Item",
            filters: { item_group: item_group },
            fields: ["item_code", "item_name", "creation"],
            order_by: "creation desc",
            limit_page_length: 10,
        },
        callback: function (r) {
            var rows = r.message || [];
            if (!rows.length) {
                frappe.show_alert({
                    message: __("No existing items in this group yet."),
                    indicator: "blue",
                });
                return;
            }

            var html = '<div style="max-height:300px; overflow-y:auto;">' +
                '<table class="table table-bordered">' +
                    '<thead><tr>' +
                        '<th>' + __("Item Code") + '</th>' +
                        '<th>' + __("Item Name") + '</th>' +
                        '<th>' + __("Created") + '</th>' +
                    '</tr></thead>' +
                    '<tbody>';

            rows.forEach(function (row) {
                html +=
                    '<tr>' +
                        '<td>' + frappe.utils.escape_html(row.item_code) + '</td>' +
                        '<td>' + frappe.utils.escape_html(row.item_name || "") + '</td>' +
                        '<td>' + frappe.datetime.str_to_user(row.creation) + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table></div>';

            frappe.msgprint({
                title: __('Recent items in "{0}"', [item_group]),
                message: html,
                indicator: "blue",
            });
        },
    });
}

function check_uom_lock(frm) {
    if (frm._uom_check_done) return;
    frm._uom_check_done = true;

    // ERPNext sets stock_exists on every item load — no extra API call needed
    const has_transactions = frm.doc.__onload && frm.doc.__onload.stock_exists;

    if (has_transactions) {
        apply_uom_lock(frm);
    }
}

function apply_uom_lock(frm) {

    const roles    = frappe.user_roles;
    const is_admin = frappe.session.user === 'Administrator'
                  || roles.includes('System Manager');

    frm.set_df_property('stock_uom', 'read_only', 1);

    frm.dashboard.add_comment(
        '🔒 Default UOM is locked — this item has stock transactions. '
        + 'Changing UOM would corrupt the stock ledger.',
        'red',
        true
    );
    frm.dashboard.show();

    if (is_admin) {
        frm.add_custom_button(__('🔓 Override UOM (Admin)'), function() {

            let d = new frappe.ui.Dialog({
                title: 'Admin Override — Change Default UOM',
                fields: [
                    {
                        label: 'New UOM',
                        fieldname: 'new_uom',
                        fieldtype: 'Link',
                        options: 'UOM',
                        reqd: 1
                    },
                    {
                        label: 'Reason for Change',
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        reqd: 1,
                        description: 'This reason will be stored in the audit trail.'
                    }
                ],
                primary_action_label: 'Confirm Override',
                primary_action: function(values) {

                    if (!values.reason || values.reason.trim().length < 10) {
                        frappe.msgprint({
                            title: 'Reason Required',
                            message: 'Please provide a detailed reason (min 10 characters).',
                            indicator: 'red'
                        });
                        return;
                    }

                    frm.set_df_property('stock_uom', 'read_only', 0);
                    frm.set_value('stock_uom', values.new_uom);
                    frm.doc.custom_uom_override_reason = values.reason;
                    frm.doc.custom_uom_overridden_by   = frappe.session.user;
                    frm.doc.custom_uom_override_date   = frappe.datetime.now_datetime();
                    frm.refresh_field('custom_uom_override_reason');

                    frappe.msgprint({
                        title: 'UOM Override Applied',
                        message: 'UOM changed to <b>' + values.new_uom
                               + '</b>. Please Save the item to confirm.',
                        indicator: 'orange'
                    });

                    d.hide();
                }
            });

            d.show();

        }, __('Admin'));
    }

    // UOM conversion table stays editable
    frm.set_df_property('uoms', 'read_only', 0);
}
