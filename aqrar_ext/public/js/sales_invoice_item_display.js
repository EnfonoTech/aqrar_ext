frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        frm.trigger("apply_item_display_mode");
    },
    apply_item_display_mode: function (frm) {
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Aqrar Settings",
                fieldname: "item_display_mode",
            },
            callback: function (r) {
                var mode = (r && r.message) ? r.message.item_display_mode : "Item Name + Description";
                update_grid_columns(frm, mode);
            },
        });
    },
});

function update_grid_columns(frm, mode) {
    var grid = frm.fields_dict.items.grid;

    if (mode === "Item Code") {
        grid.set_column_disp("item_code", true);
        grid.set_column_disp("item_name", false);
        grid.set_column_disp("description", false);
    } else if (mode === "Item Name") {
        grid.set_column_disp("item_code", false);
        grid.set_column_disp("item_name", true);
        grid.set_column_disp("description", false);
    } else if (mode === "Item Code + Description") {
        grid.set_column_disp("item_code", true);
        grid.set_column_disp("item_name", false);
        grid.set_column_disp("description", true);
    } else {
        grid.set_column_disp("item_code", false);
        grid.set_column_disp("item_name", true);
        grid.set_column_disp("description", true);
    }
}
