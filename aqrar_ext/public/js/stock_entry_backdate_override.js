// aqrar_ext: Stock Entry — "Stock Transfer Backdate Applied" is read-only for everybody
// except Stock Manager / System Manager, and only while the entry is a saved Draft.
// Untick it to keep the posting date as entered; tick it again to date the draft on the
// next save. The server refuses a change by any other user
// (utils/stock_transfer_backdate.py), this only mirrors that in the form.

frappe.ui.form.on("Stock Entry", {
    refresh: function (frm) {
        if (!frm.fields_dict.custom_stock_transfer_backdated) return;

        var allowed =
            frm.doc.docstatus === 0 &&
            !frm.is_new() &&
            frappe.user.has_role(["Stock Manager", "System Manager"]);
        frm.set_df_property("custom_stock_transfer_backdated", "read_only", allowed ? 0 : 1);
    },
});
