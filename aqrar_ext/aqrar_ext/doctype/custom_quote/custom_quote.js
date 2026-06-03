// Copyright (c) 2026, Enfono and contributors
// For license information, please see license.txt

frappe.ui.form.on("Custom Quote", {

    onload(frm) {
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value("posting_date", frappe.datetime.now_datetime());
        }
        if (frm.is_new() && !frm.doc.valid_till) {
            set_valid_till(frm);
        }
        if (frm.is_new()) {
            auto_set_price_list(frm);
        }
    },

    posting_date(frm) {
        set_valid_till(frm);
    },

    customer(frm) {
        auto_set_price_list(frm);
    },

    refresh(frm) {
        calculate_net_total(frm);
    }
});

// ── Auto-set selling price list from Customer default ─────────────────
function auto_set_price_list(frm) {
    if (!frm.doc.customer) return;

    frappe.db.get_value("Customer", frm.doc.customer, "default_price_list", function (r) {
        var cust_pl = r && r.default_price_list ? r.default_price_list : null;
        if (cust_pl) {
            frappe.db.get_value("Price List", cust_pl, "enabled", function (pl) {
                if (pl && pl.enabled) {
                    frm.set_value("selling_price_list", cust_pl);
                } else {
                    frm.set_value("selling_price_list", "Standard Selling");
                }
            });
        } else {
            frm.set_value("selling_price_list", "Standard Selling");
        }
    });
}

// ── Custom Quote Item handlers ────────────────────────────────────────
frappe.ui.form.on("Custom Quote Item", {

    item_code(frm, cdt, cdn) {
        fetch_item_details(frm, cdt, cdn);
    },

    qty(frm, cdt, cdn) {
        calculate_row(frm, cdt, cdn);
    },

    rate(frm, cdt, cdn) {
        calculate_row(frm, cdt, cdn);
    },

    tax_rate(frm, cdt, cdn) {
        calculate_row(frm, cdt, cdn);
    },

    items_remove(frm) {
        calculate_net_total(frm);
    }
});

// ── Fetch item description, UOM, and rate from Item Price ─────────────
function fetch_item_details(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (!row.item_code) return;

    frappe.db.get_value("Item", row.item_code, ["item_name", "stock_uom"], function (r) {
        if (r) {
            if (!row.item) frappe.model.set_value(cdt, cdn, "item", r.item_name);
            if (!row.unit) frappe.model.set_value(cdt, cdn, "unit", r.stock_uom);
        }
    });

    // Fetch rate from Item Price for the current selling_price_list
    var price_list = frm.doc.selling_price_list;
    if (!price_list) return;

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Item Price",
            filters: {
                item_code: row.item_code,
                price_list: price_list,
                selling: 1,
            },
            fields: ["price_list_rate", "uom"],
            limit: 1,
        },
        callback: function (res) {
            if (res.message && res.message.length) {
                var ip = res.message[0];
                if (row.rate === undefined || row.rate === 0) {
                    frappe.model.set_value(cdt, cdn, "rate", ip.price_list_rate);
                }
                if (!row.unit && ip.uom) {
                    frappe.model.set_value(cdt, cdn, "unit", ip.uom);
                }
            }
        },
    });
}

// ── Row calculations ──────────────────────────────────────────────────
function set_valid_till(frm) {
    if (!frm.doc.posting_date) return;
    frm.set_value("valid_till", frappe.datetime.add_days(frm.doc.posting_date, 30));
}

function calculate_row(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let qty = row.qty || 0;
    let rate = row.rate || 0;
    let tax_rate = row.tax_rate || 0;

    row.total = qty * rate;
    row.vat = (row.total * tax_rate) / 100;
    row.total_incl_vat = row.total + row.vat;

    frm.refresh_field("items");
    calculate_net_total(frm);
}

function calculate_net_total(frm) {
    let net_total = 0;
    let vat_total = 0;
    let grand_total = 0;

    (frm.doc.items || []).forEach(row => {
        net_total += row.total || 0;
        vat_total += row.vat || 0;
        grand_total += row.total_incl_vat || 0;
    });

    frm.set_value("net_total", net_total);
    frm.set_value("vat_total", vat_total);
    frm.set_value("grand_total", grand_total);
}
