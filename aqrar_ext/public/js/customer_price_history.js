// CR-006: Per-customer Last Price column.
//
// The Price Assist popup that used to live here is gone — fateh_trading owns
// that feature now, and two implementations on the same grid fought over one
// "Price Assist" button label. This file no longer pre-sets fateh_trading's
// guard flags (__price_assist_row_bound, __price_assist_btn_added,
// price_history_btn_added) either, so its row tracking and its Price Assist /
// Show Price History / Show Purchase History buttons all work normally.
//
// What stays here has no counterpart in fateh_trading: the Last Price column
// (custom_last_price, shipped as a Custom Field fixture) and the Branch User
// simplified Sales Invoice view.

const DOCTYPE_CONFIG = {
    "Sales Invoice":    { child_doctype: "Sales Invoice Item",    customer_field: "customer",   source: "sales"    },
    "Delivery Note":    { child_doctype: "Delivery Note Item",    customer_field: "customer",   source: "sales"    },
    "Sales Order":      { child_doctype: "Sales Order Item",      customer_field: "customer",   source: "sales"    },
    "Quotation":        { child_doctype: "Quotation Item",        customer_field: "party_name", source: "sales"    },
    "Purchase Invoice": { child_doctype: "Purchase Invoice Item", customer_field: "supplier",   source: "purchase" },
    "Purchase Order":   { child_doctype: "Purchase Order Item",   customer_field: "supplier",   source: "purchase" },
    "Purchase Receipt": { child_doctype: "Purchase Receipt Item", customer_field: "supplier",   source: "purchase" },
};

for (const [doctype, config] of Object.entries(DOCTYPE_CONFIG)) {

    frappe.ui.form.on(doctype, {

        refresh(frm) {
            update_all_last_prices(frm, config);
        },

        [config.customer_field](frm) {
            update_all_last_prices(frm, config);
        }
    });

    frappe.ui.form.on(config.child_doctype, {

        item_code(frm, cdt, cdn) {
            const row = locals[cdt][cdn];
            if (row && row.item_code) update_row_last_price(frm, row, config);
        }
    });
}

// ── Last Price column ─────────────────────────────────────────────────────

// One request per document, not one per row: a 40-line invoice used to fire
// 40 separate calls on every refresh.
function update_all_last_prices(frm, config) {
    if (frm.doc.docstatus !== 0) return;

    const rows = (frm.doc.items || []).filter(row => row.item_code);
    if (!rows.length) return;

    const item_codes = [...new Set(rows.map(row => row.item_code))];

    frappe.call({
        method: "aqrar_ext.api.get_last_sold_prices",
        args: {
            customer: frm.doc[config.customer_field],
            item_codes: JSON.stringify(item_codes),
            source: config.source,
        },
        callback(r) {
            if (r.exc || !r.message) return;
            if (frm.doc.docstatus !== 0) return;
            rows.forEach(row => {
                frappe.model.set_value(
                    row.doctype, row.name, "custom_last_price", r.message[row.item_code] || 0
                );
            });
        },
    });
}

function update_row_last_price(frm, row, config) {
    if (frm.doc.docstatus !== 0 || !row.item_code) return;

    frappe.call({
        method: "aqrar_ext.api.get_last_sold_price",
        args: {
            customer: frm.doc[config.customer_field],
            item_code: row.item_code,
            source: config.source,
        },
        callback(r) {
            if (r.exc || !r.message) return;
            frappe.model.set_value(
                row.doctype, row.name, "custom_last_price", r.message.last_price || 0
            );
        },
    });
}

// ── Branch User: simplified Sales Invoice view ────────────────────────────

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (
            !frappe.user.has_role("Branch User") ||
            frappe.user.has_role("System Manager") ||
            frappe.user.has_role("Stock Manager") ||
            frm._branch_setup_done
        ) return;
        frm._branch_setup_done = true;

        [
            "posting_time", "set_posting_time", "due_date",
            "is_pos", "pos_profile", "is_return", "is_debit_note",
            "return_against", "amended_from", "scan_barcode",
            "currency", "conversion_rate", "selling_price_list", "price_list_currency",
            "plc_conversion_rate", "ignore_pricing_rule",
            "apply_discount_on", "additional_discount_percentage", "discount_amount",
            "additional_discount_account", "base_discount_amount",
            "tax_category", "taxes_and_charges", "shipping_rule", "incoterm", "named_place",
            "taxes", "total_taxes_and_charges", "base_total_taxes_and_charges",
            "update_stock", "set_warehouse", "set_target_warehouse",
            "po_no", "po_date", "commission_rate", "total_commission", "sales_partner",
            "amount_eligible_for_commission",
            "is_cash_or_non_trade_discount",
            // accounting_dimensions_section fields — hide all except project
            "dimension_col_break", "cost_center", "is_consolidated", "is_internal_customer",
            "company_tax_id", "unrealized_profit_loss_account", "represents_company",
            "disable_rounded_total", "dispatch_address_name", "dispatch_address",
            "ignore_default_payment_terms_template", "total_billing_hours",
            "subscription",
        ].forEach(function (f) { frm.set_df_property(f, "hidden", 1); });

        // Hide sections (accounting_dimensions_section kept visible so project field shows)
        [
            "currency_and_price_list",
            "section_break_49", "taxes_section", "customer_po_details",
            "more_info", "sales_team_section_break", "section_break2",
            "edit_printing_settings", "more_information", "subscription_section",
        ].forEach(s => frm.set_df_property(s, "hidden", 1));

        ["payments_tab", "contact_and_address_tab", "terms_tab", "more_info_tab"]
            .forEach(t => frm.set_df_property(t, "hidden", 1));

        frm.set_df_property("naming_series", "reqd", 0);
        frm.set_df_property("naming_series", "hidden", 1);
        $(frm.fields_dict.naming_series.wrapper).hide();

        frm.set_df_property("company", "read_only", 1);

        if (frm.doc.docstatus === 0 && !frm.doc.cost_center) {
            frappe.call({
                method: "aqrar_ext.api.branch_config.get_user_branch_defaults",
                callback(r) {
                    if (frm.doc.docstatus !== 0) return;
                    if (r.message?.cost_center) frm.set_value("cost_center", r.message.cost_center);
                    if (r.message?.warehouse && !frm.doc.set_warehouse) frm.set_value("set_warehouse", r.message.warehouse);
                }
            });
        }
    }
});
