// aqrar_ext: Stock Entry — "Stock Transfer Backdate Applied" is read-only for everybody
// except users holding the Company's "Role Allowed to Untick Backdate", and only while the
// entry is a saved Draft. With no role set on the Company it is read-only for all.
// Untick it to keep the posting date as entered; tick it again to date the draft on the
// next save. The role is read from the Company every time the form refreshes, so a change in
// the Company applies at once. The server refuses a change by any other user
// (utils/stock_transfer_backdate.py); this only mirrors that in the form.

var SE_BACKDATE_FIELD = "custom_stock_transfer_backdated";

frappe.ui.form.on("Stock Entry", {
    refresh: function (frm) {
        if (!frm.fields_dict[SE_BACKDATE_FIELD]) return;

        frm.set_df_property(SE_BACKDATE_FIELD, "read_only", 1);
        if (frm.doc.docstatus !== 0 || frm.is_new() || !frm.doc.company) return;

        var company = frm.doc.company;
        frappe.db
            .get_value("Company", company, "custom_stock_transfer_untick_role")
            .then(function (r) {
                // the form may have moved on while the request was out
                if (frm.doc.company !== company) return;
                var role = r && r.message && r.message.custom_stock_transfer_untick_role;
                var allowed = !!role && frappe.user.has_role(role);
                frm.set_df_property(SE_BACKDATE_FIELD, "read_only", allowed ? 0 : 1);
            });
    },
});
