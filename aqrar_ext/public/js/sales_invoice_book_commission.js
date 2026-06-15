frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		if (frm.doc.__islocal || frm.doc.docstatus !== 1) return;

		frm.add_custom_button(__("Commission JE"), function () {
			frappe._aqrar_commission_si = frm.doc.name;
			frappe.new_doc("Journal Entry");
		});
	},
});
