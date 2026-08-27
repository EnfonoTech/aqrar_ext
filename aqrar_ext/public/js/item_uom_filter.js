// CR-035: the UOM dropdown on a transaction row lists only the UOMs configured
// on that Item (stock UOM + its UOM Conversion Detail rows), never the global
// UOM master.

const AQRAR_UOM_PARENTS = {
    "Sales Invoice": "items",
    "Sales Order": "items",
    "Delivery Note": "items",
    "Quotation": "items",
    "Purchase Invoice": "items",
    "Purchase Order": "items",
    "Purchase Receipt": "items",
    "Material Request": "items",
    "Stock Entry": "items",
};

Object.keys(AQRAR_UOM_PARENTS).forEach(function (doctype) {
    const grid_field = AQRAR_UOM_PARENTS[doctype];

    frappe.ui.form.on(doctype, {
        onload: function (frm) {
            // Only the editable transaction UOM. `stock_uom` is fetched from the
            // item and read-only, so it needs no query.
            apply_uom_query(frm, grid_field, "uom");
        },
    });
});

function apply_uom_query(frm, grid_field, fieldname) {
    if (!frm.fields_dict[grid_field]) return;
    const grid = frm.fields_dict[grid_field].grid;
    if (!grid || !frappe.meta.get_docfield(grid.doctype, fieldname)) return;

    frm.set_query(fieldname, grid_field, function (doc, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.item_code) {
            // No item chosen yet — leave the standard list rather than
            // returning an empty dropdown the user cannot escape.
            return {};
        }
        return {
            query: "aqrar_ext.api.queries.item_uoms",
            filters: { item_code: row.item_code },
        };
    });
}
