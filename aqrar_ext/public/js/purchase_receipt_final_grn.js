frappe.ui.form.on('Purchase Receipt', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Final GRN'), function() {
                new_purchase_receipt_with_data(frm);
            }, __('Create'));
        }
    }
});

function new_purchase_receipt_with_data(frm) {

    if (!frm.doc.items || frm.doc.items.length === 0) {
        frappe.msgprint(__('No items found to carry forward.'));
        return;
    }

    // Store source data BEFORE navigating away
    let source = JSON.parse(JSON.stringify(frm.doc));
    let source_name      = frm.doc.name;
    let source_docstatus = frm.doc.docstatus;

    // Navigate to new Purchase Receipt
    frappe.new_doc('Purchase Receipt');

    // Wait for form to fully render
    setTimeout(function() {
        populate_new_form(source, source_name, source_docstatus);
    }, 1500);
}

function populate_new_form(source, source_name, source_docstatus) {
    let new_frm = cur_frm;

    if (!new_frm || new_frm.doctype !== 'Purchase Receipt') {
        setTimeout(function() { populate_new_form(source, source_name, source_docstatus); }, 500);
        return;
    }

    //Helper: safe set value
    function s(field, value) {
        try {
            if (new_frm.fields_dict[field] !== undefined && value) {
                new_frm.doc[field] = value;
            }
        } catch(e) {}
    }

    //Header
    s('company',                source.company);
    s('supplier',               source.supplier);
    s('supplier_name',          source.supplier_name);
    s('currency',               source.currency);
    s('conversion_rate',        source.conversion_rate);
    s('buying_price_list',      source.buying_price_list);
    s('price_list_currency',    source.price_list_currency);
    s('plc_conversion_rate',    source.plc_conversion_rate);
    s('set_warehouse',          source.set_warehouse);
    s('cost_center',            source.cost_center);
    s('project',                source.project);
    s('is_subcontracted',       source.is_subcontracted);
    s('apply_putaway_rule',     source.apply_putaway_rule);
    s('ignore_pricing_rule',    source.ignore_pricing_rule);
    s('letter_head',            source.letter_head);
    s('tc_name',                source.tc_name);
    s('terms',                  source.terms);
    s('remarks',                source.remarks);
    s('taxes_and_charges',      source.taxes_and_charges);
    s('lr_no',                  source.lr_no);
    s('lr_date',                source.lr_date);
    s('supplier_delivery_note', source.supplier_delivery_note);

    //Address & Contact
    s('supplier_address',       source.supplier_address);
    s('contact_person',         source.contact_person);
    s('contact_email',          source.contact_email);
    s('shipping_address',       source.shipping_address);
    s('billing_address',        source.billing_address);

    // Store source info for after_save
    new_frm._source_name      = source_name;
    new_frm._source_docstatus = source_docstatus;

    //ITEMS
    new_frm.doc.items = [];

    (source.items || []).forEach(function(item, idx) {
        let row = frappe.model.add_child(new_frm.doc, 'Purchase Receipt Item', 'items');
        row.idx                         = idx + 1;
        row.item_code                   = item.item_code;
        row.item_name                   = item.item_name;
        row.description                 = item.description;
        row.item_group                  = item.item_group;
        row.brand                       = item.brand;
        row.qty                         = item.qty;
        row.received_qty                = item.qty;
        row.rejected_qty                = 0;
        row.uom                         = item.uom;
        row.stock_uom                   = item.stock_uom;
        row.conversion_factor           = item.conversion_factor;
        row.stock_qty                   = item.stock_qty;
        row.rate                        = item.rate;
        row.amount                      = item.amount;
        row.base_rate                   = item.base_rate;
        row.base_amount                 = item.base_amount;
        row.price_list_rate             = item.price_list_rate;
        row.discount_percentage         = item.discount_percentage;
        row.discount_amount             = item.discount_amount;
        row.warehouse                   = item.warehouse || source.set_warehouse;
        row.rejected_warehouse          = item.rejected_warehouse;
        row.expense_account             = item.expense_account;
        row.cost_center                 = item.cost_center;
        row.project                     = item.project;
        row.purchase_order              = item.purchase_order;
        row.purchase_order_item         = item.purchase_order_item;
        row.is_free_item                = item.is_free_item;
        row.batch_no                    = item.batch_no;
        row.serial_no                   = item.serial_no;
        row.weight_per_unit             = item.weight_per_unit;
        row.weight_uom                  = item.weight_uom;
        row.total_weight                = item.total_weight;
        row.valuation_rate              = item.valuation_rate;
        row.allow_zero_valuation_rate   = item.allow_zero_valuation_rate;
    });

    //TAXES
    new_frm.doc.taxes = [];

    (source.taxes || []).forEach(function(tax, idx) {
        let row = frappe.model.add_child(new_frm.doc, 'Purchase Taxes and Charges', 'taxes');
        row.idx                     = idx + 1;
        row.charge_type             = tax.charge_type;
        row.account_head            = tax.account_head;
        row.description             = tax.description;
        row.cost_center             = tax.cost_center;
        row.rate                    = tax.rate;
        row.tax_amount              = tax.tax_amount;
        row.total                   = tax.total;
        row.included_in_print_rate  = tax.included_in_print_rate;
        row.row_id                  = tax.row_id;
    });

    //Refresh all fields
    new_frm.refresh_fields();
    new_frm.refresh_field('items');
    new_frm.refresh_field('taxes');

    // Set posting date/time AFTER refresh_fields so it doesn't get reset
    if (source.posting_date) {
        // Parse date/time parts manually and build the Date via the numeric
        // constructor - string-based `new Date(dateStr + 'T' + timeStr)` parsing
        // is inconsistently strict across browsers and silently yields an
        // Invalid Date (NaN) on malformed/edge-case input.
        var dateParts = String(source.posting_date).split('-').map(Number);
        var timeParts = String(source.posting_time || '00:00:00').split('.')[0].split(':').map(Number);
        var valid = dateParts.length === 3 && timeParts.length === 3 &&
            dateParts.every(function(n) { return !isNaN(n); }) &&
            timeParts.every(function(n) { return !isNaN(n); });

        if (valid) {
            var dt = new Date(dateParts[0], dateParts[1] - 1, dateParts[2], timeParts[0], timeParts[1], timeParts[2]);
            dt.setMinutes(dt.getMinutes() - 10);
            var nd = dt.getFullYear() + '-' +
                     String(dt.getMonth() + 1).padStart(2, '0') + '-' +
                     String(dt.getDate()).padStart(2, '0');
            var nt = String(dt.getHours()).padStart(2, '0') + ':' +
                     String(dt.getMinutes()).padStart(2, '0') + ':' +
                     String(dt.getSeconds()).padStart(2, '0');
            new_frm.doc.set_posting_time = 1;
            new_frm.doc.posting_date = nd;
            new_frm.doc.posting_time = nt;
            new_frm.refresh_field('set_posting_time');
            new_frm.refresh_field('posting_date');
            new_frm.refresh_field('posting_time');
        } else {
            console.error('Final GRN: could not parse source posting date/time, leaving defaults', source.posting_date, source.posting_time);
        }
    }

    try { new_frm.script_manager.trigger('calculate_taxes_and_totals'); } catch(e) {}

    frappe.show_alert({
        message: __('Data carried forward from ' + source_name + '. Save to auto-cancel original.'),
        indicator: 'blue'
    }, 5);
}

//Auto-cancel original when new receipt is SAVED
frappe.ui.form.on('Purchase Receipt', {
    after_save: function(frm) {
        let source_name      = frm._source_name;
        let source_docstatus = frm._source_docstatus;

        if (!source_name) return;

        if (source_docstatus === 1) {
            frappe.call({
                method: 'frappe.client.cancel',
                args: { doctype: 'Purchase Receipt', name: source_name },
                callback: function(r) {
                    if (!r.exc) {
                        frappe.show_alert({
                            message: __(source_name + ' automatically cancelled.'),
                            indicator: 'green'
                        }, 6);
                        frm._source_name = null;
                    } else {
                        frappe.msgprint(__('Could not auto-cancel ' + source_name + '. Please cancel manually.'));
                    }
                }
            });
        } else if (source_docstatus === 0) {
            frappe.call({
                method: 'frappe.client.delete',
                args: { doctype: 'Purchase Receipt', name: source_name },
                callback: function(r) {
                    if (!r.exc) {
                        frappe.show_alert({
                            message: __('Draft' + source_name + ' automatically deleted.'),
                            indicator: 'green'
                        }, 6);
                        frm._source_name = null;
                    } else {
                        frappe.msgprint(__('Could not delete draft ' + source_name + '. Please delete manually.'));
                    }
                }
            });
        }
    }
});
