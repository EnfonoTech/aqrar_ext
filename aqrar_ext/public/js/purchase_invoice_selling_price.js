// Standard Selling Price column on Purchase Invoice items. Shows each row's
// current general selling price (the default selling price list, in the row's
// UOM) so the buyer can change it while entering the purchase. The server writes
// changed prices to Item Price on submit
// (utils/selling_price.update_standard_selling_prices).

(function () {
    const FIELD = "custom_standard_selling_rate";

    function fetch_rates(frm, rows) {
        rows = rows.filter((row) => row.item_code && row.uom);
        if (!rows.length) return Promise.resolve();
        return frappe
            .call({
                method: "aqrar_ext.aqrar_ext.utils.selling_price.get_standard_selling_rates",
                args: { items: rows.map((row) => ({ item_code: row.item_code, uom: row.uom })) },
            })
            .then((r) => {
                const rates = (r && r.message && r.message.rates) || {};
                rows.forEach((row) => {
                    // Written straight onto the row: display state, and
                    // set_value would mark an untouched form dirty.
                    row[FIELD] = rates[row.item_code + "::" + row.uom] || 0;
                });
                frm.refresh_field("items");
            });
    }

    // Rows mapped in from a Purchase Order / Receipt, or saved before this
    // column existed, arrive empty. Fill only those, so a price the buyer has
    // already typed on a draft is never overwritten.
    function fill_empty(frm) {
        if (frm.doc.docstatus !== 0 || frm.doc.is_return) return;
        fetch_rates(frm, (frm.doc.items || []).filter((row) => !flt(row[FIELD])));
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
