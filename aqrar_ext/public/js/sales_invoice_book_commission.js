frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		if (frm.doc.__islocal || frm.doc.docstatus !== 1) return;

		frappe.call({
			method: "aqrar_ext.api.commission.get_commission_je_status",
			args: { sales_invoice: frm.doc.name },
			callback: function (r) {
				if (r.message && r.message.exists) {
					frm.add_custom_button(__("View Commission JE"), function () {
						frappe.set_route("Form", "Journal Entry", r.message.je_name);
					});
					return;
				}

				frm.add_custom_button(__("Book Commission"), function () {
					frappe.call({
						method: "aqrar_ext.api.commission.create_commission_je",
						args: { sales_invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating Commission Journal Entry..."),
						callback: function (res) {
							if (res.message) {
								frappe.set_route("Form", "Journal Entry", res.message);
							}
						},
						error: function () {
							frappe.msgprint({
								title: __("Error"),
								message: __("Failed to create Commission Journal Entry."),
								indicator: "red",
							});
						},
					});
				});
			},
			error: function () {
				frm.add_custom_button(__("Book Commission"), function () {
					frappe.call({
						method: "aqrar_ext.api.commission.create_commission_je",
						args: { sales_invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating Commission Journal Entry..."),
						callback: function (res) {
							if (res.message) {
								frappe.set_route("Form", "Journal Entry", res.message);
							}
						},
						error: function () {
							frappe.msgprint({
								title: __("Error"),
								message: __("Failed to create Commission Journal Entry."),
								indicator: "red",
							});
						},
					});
				});
			},
		});
	},
});
