frappe.provide("aqrar_ext.price_assist");

// CR-006: Per-customer Last Price column + Price Assist popup
// Popup style mirrors fateh_trading/customer_price_history.js exactly.
// Loaded via app_include_js — pre-sets fateh_trading guard flags to prevent
// duplicate buttons/handlers from fateh_trading's doctype_js version.

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
            // Block fateh_trading/customer_price_history.js duplicate buttons/handlers
            frm.__price_assist_row_bound = true;
            frm.__price_assist_btn_added = true;
            frm.price_history_btn_added  = true;

            bind_row_click(frm, config);
            add_price_assist_button(frm, config);
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
        },

        rate(frm, cdt, cdn) {
            aqrar_ext.price_assist.updateHighlight(locals[cdt][cdn]);
        }
    });
}

// ── Row click ─────────────────────────────────────────────────────────────

function bind_row_click(frm, config) {
    if (frm.__aqrar_row_click_bound) return;

    frm.fields_dict.items.grid.wrapper.on("click", ".grid-row [data-fieldname='item_code']", function () {
        const $row     = $(this).closest(".grid-row");
        const row_name = $row.attr("data-name");
        if (!row_name) return;
        const row = locals[config.child_doctype]?.[row_name];

        if (frm.__selected_price_row && frm.__selected_price_row !== row) {
            aqrar_ext.price_assist.hide(frm.__selected_price_row);
        }

        frm.__selected_price_row = row;
        frm.__price_assist_row   = row;

        if (row && row.item_code) {
            aqrar_ext.price_assist.show(frm, row, config);
        }
    });

    frm.__aqrar_row_click_bound = true;
}

// ── Price Assist button ───────────────────────────────────────────────────

function add_price_assist_button(frm, config) {
    if (frm.__aqrar_buttons_added) return;
    frm.__aqrar_buttons_added = true;

    const btn = frm.fields_dict.items.grid.add_custom_button(__("Price Assist"), () => {
        const row = frm.__selected_price_row || frm.__price_assist_row;
        if (!row || !row.item_code) {
            frappe.msgprint(__("Please click an item row first"));
            return;
        }
        aqrar_ext.price_assist.show(frm, row, config);
    });

    setTimeout(() => {
        const $toolbar      = frm.fields_dict.items.grid.wrapper.find(".grid-buttons");
        const $add_multiple = $toolbar.find("button:contains('Add Multiple')").last();
        if ($add_multiple.length && btn) $(btn).insertAfter($add_multiple);
    }, 0);
}

// ── Last Price column ─────────────────────────────────────────────────────

function update_all_last_prices(frm, config) {
    if (frm.doc.docstatus !== 0) return;
    (frm.doc.items || []).forEach(row => {
        if (row.item_code) update_row_last_price(frm, row, config);
    });
}

function update_row_last_price(frm, row, config) {
    if (frm.doc.docstatus !== 0) return;
    const party = frm.doc[config.customer_field];
    frappe.call({
        method: "aqrar_ext.api.get_last_sold_price",
        args: { customer: party, item_code: row.item_code, source: config.source },
        callback(r) {
            if (!r.message) return;
            frappe.model.set_value(row.doctype, row.name, "custom_last_price", r.message.last_price || 0);
        }
    });
}

// ── Price Assist popup (mirrors fateh_trading style exactly) ──────────────

$.extend(aqrar_ext.price_assist, {

    show(frm, row, config) {
        this.hide(row);
        const party = frm.doc[config.customer_field];
        if (!party || !row.item_code) return;

        frappe.call({
            method: "aqrar_ext.api.get_item_insights",
            args: {
                customer:    party,
                item_code:   row.item_code,
                company:     frm.doc.company,
                source:      config.source,
                limit:       6,
                other_limit: 5,
            },
            callback: r => this.render(frm, row, r.message || {}, config)
        });
    },

    render(frm, row, insights, config) {
        this.hide(row);

        const price_history   = insights.price_history   || [];
        const other_customers = insights.other_customers || [];
        const stock           = insights.stock           || [];
        const last_rate       = flt(insights.last_rate        || 0);
        const last_purchase_rate = flt(insights.last_purchase_rate || 0);
        const avg_rate        = price_history.length
            ? price_history.reduce((s, d) => s + flt(d.rate), 0) / price_history.length
            : 0;

        const id   = `aqrar-price-assist-${row.name}`;
        const $box = $(`<div class="si-price-assist" id="${id}"></div>`).appendTo("body");

        const customerField = config?.customer_field || "customer";
        const customer      = frm.doc[customerField];

        $box.append(`<div class="pa-customer">${frappe.utils.escape_html(customer)}</div>`);
        $box.append(`<div class="pa-title">Price History: ${frappe.utils.escape_html(row.item_name || row.item_code)}</div>`);

        // Summary: Last / Last Purchase / Current + % diff
        const current_rate = flt(row.stock_uom_rate ?? row.rate);
        let diff_text = "", diff_class = "";
        if (current_rate && last_rate) {
            const diff_pct = ((current_rate - last_rate) / last_rate) * 100;
            const abs      = Math.abs(diff_pct);
            diff_class = abs <= 5 ? "pa-price-good" : abs <= 20 ? "pa-price-warn" : "pa-price-bad";
            diff_text  = `${diff_pct >= 0 ? "+" : ""}${diff_pct.toFixed(1)}% vs last price`;
        }

        $box.append(`
            <div class="pa-summary ${diff_class}">
                <div class="pa-summary-main">
                    <div><label>Last</label><span>${last_rate || "-"}</span></div>
                    <div><label>Average</label><span>${avg_rate ? avg_rate.toFixed(2) : "-"}</span></div>
                    <div><label>Current</label><span>${current_rate || "-"}</span></div>
                </div>
                <div class="pa-summary-warning">${diff_text}</div>
            </div>
        `);

        // Price history rows
        price_history.forEach(d => {
            $box.append(
                $(`<div class="pa-line">
                    <div class="pa-left">
                        <b>${d.rate}</b> (${d.currency || ""}, ${d.uom || ""})
                        <small>${d.qty} qty • ${frappe.format(d.posting_date, "Date")}</small>
                        <small class="pa-inv">
                            <a href="/app/sales-invoice/${encodeURIComponent(d.si)}" target="_blank">${d.si}</a>
                        </small>
                    </div>
                    <button class="pa-use">Use</button>
                </div>`).data("rate", d.rate)
            );
        });

        // Other customers
        if (other_customers.length) {
            $box.append(`<div class="pa-section-title">Other customers paying</div>`);
            other_customers.forEach(d => {
                $box.append(
                    $(`<div class="pa-line pa-other">
                        <div class="pa-left">
                            <b>${d.rate}</b> (${d.currency || ""}, ${d.uom || ""})
                            <small>${frappe.utils.escape_html(d.customer)}</small>
                        </div>
                        <button class="pa-use">Use</button>
                    </div>`).data("rate", d.rate)
                );
            });
        }

        // Stock by warehouse
        if (stock.length) {
            $box.append(`<div class="pa-section-title">Stock by Warehouse</div>`);
            const maxQty = Math.max(...stock.map(s => flt(s.projected_qty))) || 1;
            stock.forEach(s => {
                const fill = Math.min(100, (flt(s.projected_qty) / maxQty) * 100);
                $box.append(`
                    <div class="ps-line">
                        <div class="ps-left">
                            <b>${frappe.utils.escape_html(s.warehouse)}</b>
                            <small>${s.projected_qty} available</small>
                        </div>
                        <div class="ps-bar-wrap">
                            <div class="ps-bar" style="width:${fill}%"></div>
                        </div>
                        <button class="ps-use">Use</button>
                    </div>
                `);
            });
        }

        // Position below the item_code input of the row
        const $input = $(`.grid-row[data-name="${row.name}"] input[data-fieldname="item_code"]`);
        if ($input.length) {
            const pos = $input.offset();
            $box.css({ top: pos.top + $input.outerHeight() + 8, left: pos.left });
        }

        // "Use" — apply rate
        $box.on("click", ".pa-use", function () {
            const rate = $(this).closest(".pa-line").data("rate");
            frappe.model.set_value(row.doctype, row.name, "rate", rate);
            frappe.model.set_value(row.doctype, row.name, "actual_rate", rate);
            frappe.model.set_value(row.doctype, row.name, "custom_last_price", rate);
            aqrar_ext.price_assist.hide(row);
        });

        // "Use" — apply warehouse
        $box.on("click", ".ps-use", function () {
            frappe.model.set_value(row.doctype, row.name, "warehouse",
                $(this).closest(".ps-line").find("b").text());
        });

        row._price_id = id;
    },

    updateHighlight(row) {
        if (!row || !row._price_id) return;
        const rate = flt(row.rate);
        $(`#${row._price_id} .pa-line`).each(function () {
            $(this).toggleClass("pa-match", flt($(this).data("rate")) === rate);
        });
    },

    hide(row) {
        if (row?._price_id) {
            $(`#${row._price_id}`).remove();
            delete row._price_id;
        }
    }
});

// Close popup when clicking outside
$(document).on("click.aqrar_price_assist", function (e) {
    if ($(e.target).closest(".si-price-assist").length) return;
    if ($(e.target).closest(".grid-row").length) return;
    const frm = cur_frm;
    if (frm?.__selected_price_row) {
        aqrar_ext.price_assist.hide(frm.__selected_price_row);
    }
});

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

// ── Styles (same as fateh_trading) ───────────────────────────────────────

$(`<style>
.si-price-assist{position:absolute;z-index:1050;width:340px;background:#0d1117;color:#fff;padding:14px;border-radius:12px;box-shadow:0 8px 25px rgba(0,0,0,.45);font-size:13px}
.pa-customer{font-size:12px;color:#c9d1d9;margin-bottom:4px;opacity:.85}
.pa-title{font-weight:600;font-size:14px;margin-bottom:10px;opacity:.9}
.pa-summary{border-radius:10px;padding:10px;margin-bottom:10px;background:#111b24;border:1px solid rgba(255,255,255,.06)}
.pa-summary-main{display:flex;justify-content:space-between;gap:6px}
.pa-summary-main label{display:block;font-size:10px;text-transform:uppercase;opacity:.6}
.pa-summary-main span{font-size:13px;font-weight:600}
.pa-summary-warning{margin-top:6px;font-size:11px}
.pa-price-good{border-color:rgba(0,200,120,.4)}
.pa-price-good .pa-summary-warning{color:#00e676}
.pa-price-warn{border-color:rgba(255,200,0,.4)}
.pa-price-warn .pa-summary-warning{color:#ffeb3b}
.pa-price-bad{border-color:rgba(255,80,80,.5)}
.pa-price-bad .pa-summary-warning{color:#ff5252}
.pa-section-title{font-size:11px;text-transform:uppercase;opacity:.7;margin:6px 0 4px}
.pa-line{padding:10px;margin-bottom:8px;background:#111b24;border-radius:10px;display:flex;justify-content:space-between;align-items:center;border:1px solid rgba(255,255,255,.05)}
.pa-line:hover{background:#16212c}
.pa-line.pa-match{border-color:rgba(0,230,118,.4)}
.pa-line.pa-other{opacity:.85}
.pa-left b{font-size:14px;font-weight:600}
.pa-left small{display:block;font-size:10px;opacity:.75}
.pa-inv a{color:#58a6ff;text-decoration:none}
.pa-use{padding:6px 14px;font-size:11px;border-radius:8px;border:none;background:linear-gradient(90deg,#00d2ff,#3a7bd5);color:#fff;font-weight:600;cursor:pointer}
.ps-line{padding:8px;margin-bottom:6px;background:#101820;border-radius:10px;display:flex;align-items:center;gap:8px;border:1px solid rgba(255,255,255,.06)}
.ps-left{min-width:120px}
.ps-left small{font-size:10px;opacity:.75}
.ps-bar-wrap{flex:1;height:6px;background:rgba(255,255,255,.06);border-radius:999px;overflow:hidden}
.ps-bar{height:6px;border-radius:999px;background:linear-gradient(90deg,#00e676,#00b0ff)}
.ps-use{padding:4px 10px;font-size:10px;border-radius:999px;border:none;background:#263238;color:#e0f7fa;cursor:pointer}
</style>`).appendTo("head");
