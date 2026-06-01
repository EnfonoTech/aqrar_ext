frappe.ui.form.on("Journal Entry", {
	refresh: function (frm) {
		frm.set_df_property("custom_reference_invoice", "hidden", 0);
	},
});
