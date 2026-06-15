frappe.ui.form.on("Journal Entry", {
	onload: function (frm) {
		if (!frm.doc.__islocal) return;

		const si_name = frappe._aqrar_commission_si;
		if (!si_name) return;
		delete frappe._aqrar_commission_si;

		frappe.db.get_value(
			"Sales Invoice",
			si_name,
			["customer", "posting_date", "company"],
			function (si) {
				if (!si) return;

				frm.set_value("company", si.company);
				frm.set_value("posting_date", si.posting_date);

				frm.clear_table("accounts");
				const row = frm.add_child("accounts");
				row.party_type = "Customer";
				row.party = si.customer;
				row.reference_type = "Sales Invoice";
				row.reference_name = si_name;
				frm.refresh_field("accounts");
			}
		);
	},
});
