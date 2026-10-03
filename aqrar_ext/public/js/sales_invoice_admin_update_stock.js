// aqrar_ext: Administrator always sees (and can tick) Update Stock on Sales Invoice,
// and the value it picks survives saving without the form turning "Not Saved".
//
// Administrator holds every role, including Branch User, so the role-based
// Client Scripts hide / lock the checkbox and keep calling
// frm.set_value("update_stock", 0) — on load, on customer change and after every
// save. Each of those marks the form dirty. For Administrator we ignore those
// resets: the value only changes by the user's own click (or the new-invoice
// default of ticked), so nothing is left to restore and nothing gets dirtied.

function aqrar_is_admin_draft(frm) {
    return frappe.session.user === "Administrator" && frm.doc.docstatus === 0;
}

function aqrar_guard_update_stock(frm) {
    if (frm._aqrar_us_guarded) return;
    frm._aqrar_us_guarded = true;

    var original_set_value = frm.set_value.bind(frm);
    frm.set_value = function (field, value) {
        var is_reset =
            field === "update_stock" &&
            !frm._aqrar_us_internal &&
            aqrar_is_admin_draft(frm) &&
            cint(value) !== cint(frm.doc.update_stock);
        if (is_reset) return Promise.resolve();
        return original_set_value.apply(null, arguments);
    };

    // The user's own click on the checkbox must still go through.
    var field = frm.fields_dict.update_stock;
    if (field && field.$input) {
        field.$input.on("change", function () {
            frm._aqrar_us_internal = true;
            frm.doc.update_stock = field.$input.prop("checked") ? 1 : 0;
            frm.dirty();
            frm._aqrar_us_internal = false;
        });
    }
}

function aqrar_apply_admin_update_stock(frm) {
    if (!aqrar_is_admin_draft(frm)) return;
    aqrar_guard_update_stock(frm);

    // New invoices default to ticked, like the other elevated roles.
    if (frm.is_new() && !frm._aqrar_us_defaulted) {
        frm._aqrar_us_defaulted = true;
        frm._aqrar_us_internal = true;
        frm.set_value("update_stock", 1);
        frm._aqrar_us_internal = false;
    }

    // Visibility only — these do not dirty the form.
    [0, 400, 1000, 1600].forEach(function (delay) {
        setTimeout(function () {
            frm.set_df_property("update_stock", "hidden", 0);
            frm.set_df_property("update_stock", "read_only", 0);
            frm.refresh_field("update_stock");
        }, delay);
    });
}

frappe.ui.form.on("Sales Invoice", {
    onload_post_render: aqrar_apply_admin_update_stock,
    refresh: aqrar_apply_admin_update_stock,
    customer: aqrar_apply_admin_update_stock,
});
