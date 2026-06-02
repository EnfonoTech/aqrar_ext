// Copyright (c) 2026, Enfono and contributors
// For license information, please see license.txt

frappe.ui.form.on("Branch Configuration", {
	refresh(frm) {
		set_child_filters(frm);
	},
	company(frm) {
		set_child_filters(frm);

		// Clear warehouse and cost center tables when company changes
		// (they may belong to the old company)
		if (frm.doc.warehouse && frm.doc.warehouse.length) {
			frm.clear_table("warehouse");
			frm.refresh_field("warehouse");
		}
		if (frm.doc.cost_center && frm.doc.cost_center.length) {
			frm.clear_table("cost_center");
			frm.refresh_field("cost_center");
		}
	}
});

function set_child_filters(frm) {
	frm.set_query("warehouse", "warehouse", function () {
		return {
			filters: {
				company: frm.doc.company,
				is_group: 0
			}
		};
	});

	frm.set_query("cost_center", "cost_center", function () {
		return {
			filters: {
				company: frm.doc.company,
				is_group: 0
			}
		};
	});
}
