frappe.ui.form.on("Item", {
	setup: function (frm) {
		frm.toggle_display("naming_series", false);
	},
	refresh: function (frm) {
		if (frm.doc.__islocal && frm.doc.item_group && !frm.doc._naming_applied) {
			set_naming_from_group(frm);
		}
	},
	item_group: function (frm) {
		if (!frm.doc.__islocal) return;
		if (!frm.doc.item_group) {
			frm.toggle_display("naming_series", false);
			return;
		}
		set_naming_from_group(frm);
	},
});

function set_naming_from_group(frm) {
	frappe.db.get_value("Item Group", frm.doc.item_group, "custom_default_item_naming_series", function (r) {
		if (!r || !r.custom_default_item_naming_series) {
			frm.toggle_display("naming_series", false);
			return;
		}

		frm.doc._naming_applied = true;
		frm.toggle_display("naming_series", true);
		frm.set_value("naming_series", r.custom_default_item_naming_series);
	});
}
