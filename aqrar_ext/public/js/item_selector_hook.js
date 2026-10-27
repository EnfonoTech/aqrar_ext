// aqrar_ext: Wire ItemMultiSelector into Sales Invoice, Quotation, Custom Quote, Sales Order,
// Delivery Note, Purchase Invoice, Purchase Order, Purchase Receipt,
// Material Request, Stock Entry

var doctypes_with_items = [
    "Sales Invoice",
    "Quotation",
    "Custom Quote",
    "Purchase Invoice",
    "Sales Order",
    "Delivery Note",
    "Purchase Order",
    "Purchase Receipt",
    "Material Request",
    "Stock Entry",
];

var ADD_MULTIPLE_LABEL = "Add Multiple Items";

// The Item cell of an items grid opens the item list as soon as it is clicked,
// which covers the rows and buttons under the table. Keep the list closed until
// something is typed: with the cell empty there is nothing to suggest.
//
// Awesomplete runs every refresh through evaluate(), including the one Frappe's
// Link field triggers on focus and the one after its data arrives, so one wrapper
// here covers all of them. Cells of other fields are untouched.
(function () {
    if (typeof Awesomplete === "undefined" || Awesomplete.prototype.__aqrar_item_cell) return;
    Awesomplete.prototype.__aqrar_item_cell = true;

    var evaluate = Awesomplete.prototype.evaluate;
    Awesomplete.prototype.evaluate = function () {
        var input = this.input;
        if (input && !input.value && input.closest) {
            var field = input.getAttribute("data-fieldname");
            if ((field === "item_code" || field === "item") && input.closest(".grid-row")) {
                this.close({ reason: "empty" });
                return;
            }
        }
        return evaluate.apply(this, arguments);
    };
})();

doctypes_with_items.forEach(function (doctype) {
    frappe.ui.form.on(doctype, {
        refresh: function (frm) {
            if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;

            var grid = frm.fields_dict.items.grid;

            // The button above the table follows the document: gone once it is submitted.
            var top_btn = grid.custom_buttons && grid.custom_buttons[ADD_MULTIPLE_LABEL];
            if (top_btn) top_btn.toggle(!frm.doc.docstatus);

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
            var uom_field = frappe.meta.get_docfield(child_doctype, "uom") ? "uom" : null;

            function open_selector() {
                new frappe.ui.form.ItemMultiSelector({
                    target: grid,
                    fieldname: item_field,
                    qty_fieldname: qty_field,
                    uom_fieldname: uom_field,
                });
            }

            // Clicking an Item cell opens the item list right over the buttons under
            // the table, so a click meant for "Add Multiple" landed on the first item
            // of the list. The button lives ABOVE the table instead, where the list
            // never reaches, and the one under the table is hidden.
            var btn = $(grid.wrapper).find(".grid-add-multiple-rows");
            btn.off("click.aqrar").on("click.aqrar", function (e) {
                e.stopImmediatePropagation();
                e.preventDefault();
                open_selector();
            });

            if (grid.add_custom_button) {
                btn[0] && btn[0].style.setProperty("display", "none", "important");
                grid.add_custom_button(ADD_MULTIPLE_LABEL, open_selector, "top").toggle(!frm.doc.docstatus);
            } else {
                // No top button available: keep the original one working.
                btn.removeClass("hidden");
            }
        },
    });
});
