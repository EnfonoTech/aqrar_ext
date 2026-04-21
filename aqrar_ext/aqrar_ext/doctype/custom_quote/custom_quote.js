// Copyright (c) 2026, Enfono and contributors
// For license information, please see license.txt


//Set valid till date to 30 days from posting date

frappe.ui.form.on("Custom Quote", {

    onload(frm) {
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value(
                "posting_date",
                frappe.datetime.now_datetime()
            );
        }
        if (frm.is_new() && !frm.doc.valid_till) {
            set_valid_till(frm);
        }
    },

    posting_date(frm) {
        set_valid_till(frm);
    },

    refresh(frm) {
        calculate_net_total(frm);
    }
});

//Set total vat tax include vat
frappe.ui.form.on("Custom Quote Item", {

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

function set_valid_till(frm) {
    if (!frm.doc.posting_date) return;

    frm.set_value(
        "valid_till",
        frappe.datetime.add_days(frm.doc.posting_date, 30)
    );
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

//Set net total vat total grand total
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
