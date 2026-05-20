// aqrar_ext: Wire ItemMultiSelector into Sales Invoice, Quotation, Custom Quote

var doctypes_with_items = ["Sales Invoice", "Quotation", "Custom Quote"];

doctypes_with_items.forEach(function (doctype) {
    frappe.ui.form.on(doctype, {
        refresh: function (frm) {
            if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;

            var grid = frm.fields_dict.items.grid;
            if (grid._aqrar_multisel_hooked) return;
            grid._aqrar_multisel_hooked = true;

            // Detect which field is the item link
            var child_doctype = grid.df.options;
            var item_field = frappe.meta.get_docfield(child_doctype, "item_code")
                ? "item_code"
                : frappe.meta.get_docfield(child_doctype, "item")
                ? "item"
                : null;

            if (!item_field) return;

            // Only wire up if the item field links to Item doctype
            var df = frappe.meta.get_docfield(child_doctype, item_field);
            if (!df || df.fieldtype !== "Link" || df.options !== "Item") return;

            var qty_field = frappe.meta.get_docfield(child_doctype, "qty") ? "qty" : null;

            var btn = $(grid.wrapper).find(".grid-add-multiple-rows");
            btn.removeClass("hidden");
            btn.off("click.aqrar").on("click.aqrar", function (e) {
                e.stopImmediatePropagation();
                e.preventDefault();
                new frappe.ui.form.ItemMultiSelector({
                    target: grid,
                    fieldname: item_field,
                    qty_fieldname: qty_field,
                });
            });
        },
    });
});
