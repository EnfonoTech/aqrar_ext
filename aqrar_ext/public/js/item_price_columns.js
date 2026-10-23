// Standard Selling Price / Wholesale Price columns on the Purchase Invoice item table.
// Each row shows the current general price (the default
// selling price list and the Wholesale Price List from Selling Settings, in the
// row's UOM). The buyer can change them (Price List Editor role only)
// and the server writes changed prices to Item Price on submit
// (utils/selling_price.update_standard_selling_prices).

(function () {
    const FIELD = "custom_standard_selling_rate";
    const WHOLESALE_FIELD = "custom_wholesale_selling_rate";
    const PRICE_FIELDS = [FIELD, WHOLESALE_FIELD];

    function fetch_rates(frm, rows) {
        rows = rows.filter((row) => row.item_code && row.uom);
        if (!rows.length) return Promise.resolve();
        return frappe
            .call({
                method: "aqrar_ext.aqrar_ext.utils.selling_price.get_standard_selling_rates",
                args: { items: rows.map((row) => ({ item_code: row.item_code, uom: row.uom })) },
            })
            .then((r) => {
                const msg = (r && r.message) || {};
                const rates = msg.rates || {};
                const wholesale = msg.wholesale_rates || {};
                rows.forEach((row) => {
                    // Written straight onto the row: display state, and
                    // set_value would mark an untouched form dirty.
                    const key = row.item_code + "::" + row.uom;
                    row[FIELD] = rates[key] || 0;
                    row[WHOLESALE_FIELD] = wholesale[key] || 0;
                });
                lock_price_fields(frm, msg.can_edit);
                frm.refresh_field("items");
            });
    }

    // Rows mapped in from a Purchase Order / Receipt, or saved before this
    // column existed, arrive empty. Fill only those, so a price the buyer has
    // already typed on a draft is never overwritten.
    // Only users with the Price List Editor role may change these prices;
    // everyone else sees them read-only (the server ignores their edits too).
    function lock_price_fields(frm, can_edit) {
        if (can_edit === undefined) {
            can_edit = frappe.user.has_role("Price List Editor") || frappe.session.user === "Administrator";
        }
        const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
        if (!grid) return;
        PRICE_FIELDS.forEach((f) => grid.update_docfield_property(f, "read_only", can_edit ? 0 : 1));
    }

    function fill_empty(frm) {
        lock_price_fields(frm);
        if (frm.doc.docstatus !== 0 || frm.doc.is_return) return;
        fetch_rates(frm, (frm.doc.items || []).filter((row) => !flt(row[FIELD]) && !flt(row[WHOLESALE_FIELD])));
    }

    // A new item or UOM is a different price: load the one that belongs to it.
    // On a new item ERPNext fills uom from the item details by plain assignment
    // (no uom event) some time after its own calls return, so wait until the
    // row actually carries the item's UOM before looking the price up.
    function reload_row(frm, cdt, cdn) {
        if (frm.doc.is_return) return;
        const item_code = (locals[cdt][cdn] || {}).item_code;
        let tries = 0;
        const attempt = () =>
            frappe.after_ajax(() => {
                const row = locals[cdt][cdn];
                if (!row || row.item_code !== item_code) return;
                if (!row.uom && tries++ < 20) return setTimeout(attempt, 150);
                fetch_rates(frm, [row]);
            });
        attempt();
    }

    frappe.ui.form.on("Purchase Invoice", {
        onload: fill_empty,
        refresh: fill_empty,
    });
    frappe.ui.form.on("Purchase Invoice Item", {
        item_code: reload_row,
        uom: reload_row,
    });
})();
