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
    }

});

function check_uom_lock(frm) {
    if (frm._uom_check_done) return;  // ← add this
    frm._uom_check_done = true;

    // Check if item has any stock transactions
    frappe.call({
        method: 'frappe.client.get_count',
        args: {
            doctype: 'Stock Ledger Entry',
            filters: {
                item_code: frm.doc.name,
                is_cancelled: 0
            }
        },
        callback: function(r) {
            const has_transactions = r.message > 0;

            if (has_transactions) {
                apply_uom_lock(frm);
            }
        }
    });
}

function apply_uom_lock(frm) {

    const roles        = frappe.user_roles;
    const is_admin     = frappe.session.user === 'Administrator'
                      || roles.includes('System Manager');

    // ── Req 77: Lock default_uom ──────────────────────────────────────
    frm.set_df_property('stock_uom', 'read_only', 1);

    frm.dashboard.add_comment(
        '🔒 Default UOM is locked — this item has stock transactions. '
        + 'Changing UOM would corrupt the stock ledger.',
        'red',
        true
    );
    frm.dashboard.show();

    // ── Req 78: Admin override button ────────────────────────────────
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

                    // Unlock field temporarily
                    frm.set_df_property('stock_uom', 'read_only', 0);
                    frm.set_value('stock_uom', values.new_uom);
                    frm.set_value('custom_uom_override_reason', values.reason);
                    frm.set_value('custom_uom_overridden_by', frappe.session.user);
                    frm.set_value(
                        'custom_uom_override_date',
                        frappe.datetime.now_datetime()
                    );

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

    // ── Req 79: Additional UOMs still editable ───────────────────────
    // UOM conversion table (uoms child table) stays editable
    frm.set_df_property('uoms', 'read_only', 0);
}