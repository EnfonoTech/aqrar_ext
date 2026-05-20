frappe.provide("aqrar_ext.price_assist");

const DOCTYPE_CONFIG = {
    "Sales Invoice": {
        child_doctype: "Sales Invoice Item",
        customer_field: "customer",
        source: "sales"
    },
    "Delivery Note": {
        child_doctype: "Delivery Note Item",
        customer_field: "customer",
        source: "sales"
    },
    "Sales Order": {
        child_doctype: "Sales Order Item",
        customer_field: "customer",
        source: "sales"
    },
    "Quotation": {
        child_doctype: "Quotation Item",
        customer_field: "party_name",
        source: "sales"
    },
    "Purchase Invoice": {
        child_doctype: "Purchase Invoice Item",
        customer_field: "supplier",
        source: "purchase"
    },
    "Purchase Order": {
        child_doctype: "Purchase Order Item",
        customer_field: "supplier",
        source: "purchase"
    },
    "Purchase Receipt": {
        child_doctype: "Purchase Receipt Item",
        customer_field: "supplier",
        source: "purchase"
    },
};

for (const [doctype, config] of Object.entries(DOCTYPE_CONFIG)) {

    frappe.ui.form.on(doctype, {

        refresh(frm) {

            bind_row_click(frm, config);

            add_price_assist_button(frm, config);

            add_price_history_button(frm, config);

            update_all_last_prices(frm, config);
        },

        [config.customer_field](frm) {
            update_all_last_prices(frm, config);
        }
    });

    frappe.ui.form.on(config.child_doctype, {

        item_code(frm, cdt, cdn) {

            const row = locals[cdt][cdn];

            if (!row.item_code) return;

            update_row_last_price(frm, row, config);
        },

        rate(frm, cdt, cdn) {

            const row = locals[cdt][cdn];

            if (row._popup_opened) {
                show_price_popup(frm, row, config);
            }
        }
    });
}

function bind_row_click(frm, config) {

    if (frm.__price_row_bound) return;

    frm.fields_dict.items.grid.wrapper.on(
        "click",
        ".grid-row",
        function () {

            const row_name = $(this).attr("data-name");

            if (!row_name) return;

            const row = locals[config.child_doctype][row_name];

            frm.__selected_price_row = row;

            // Auto-show popup on row click when item_code is set
            if (row && row.item_code) {
                show_price_popup(frm, row, config);
            }
        }
    );

    frm.__price_row_bound = true;
}

function add_price_assist_button(frm, config) {

    if (frm.__price_btn_added) return;

    const btn = frm.fields_dict.items.grid.add_custom_button(
        __("Price Assist"),
        () => {

            const row = frm.__selected_price_row;

            if (!row) {
                frappe.msgprint("Please select an item row");
                return;
            }

            if (!row.item_code) {
                frappe.msgprint("Please select item code");
                return;
            }

            show_price_popup(frm, row, config);
        }
    );

    frm.__price_btn_added = true;

    setTimeout(() => {

        const $toolbar =
            frm.fields_dict.items.grid.wrapper.find(".grid-buttons");

        const $add_multiple =
            $toolbar.find("button:contains('Add Multiple')").last();

        if ($add_multiple.length) {
            $(btn).insertAfter($add_multiple);
        }

    }, 100);
}

function add_price_history_button(frm, config) {

    if (frm.__price_history_btn_added) return;

    const btn = frm.fields_dict.items.grid.add_custom_button(
        __("Price History"),
        () => {

            const row = frm.__selected_price_row;

            if (!row) {
                frappe.msgprint("Please select an item row");
                return;
            }

            if (!row.item_code) {
                frappe.msgprint("Please select item code");
                return;
            }

            const party = frm.doc[config.customer_field];
            show_price_history_dialog(row.item_code, config.source, party);
        }
    );

    frm.__price_history_btn_added = true;

    setTimeout(() => {

        const $toolbar =
            frm.fields_dict.items.grid.wrapper.find(".grid-buttons");

        const $price_assist =
            $toolbar.find("button:contains('Price Assist')").last();

        if ($price_assist.length) {
            $(btn).insertAfter($price_assist);
        }

    }, 100);
}

function show_price_history_dialog(item_code, source, customer) {

    source = source || "sales";
    const party_label = source === "purchase" ? __("Supplier") : __("Customer");

    const d = new frappe.ui.Dialog({
        title: __("Item Sales & Purchase Price History"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "Link",
                fieldname: "item_code",
                label: __("Item Code"),
                options: "Item",
                default: item_code,
            },
            {
                fieldtype: "HTML",
                fieldname: "history_table",
            },
        ],
    });

    d.show();

    function load_table(code) {
        if (!code) {
            d.fields_dict.history_table.$wrapper.html(
                '<p class="text-muted">' + __("Please select an Item Code") + "</p>"
            );
            return;
        }

        d.fields_dict.history_table.$wrapper.html(
            '<p class="text-muted">' + __("Loading...") + "</p>"
        );

        frappe.call({
            method: "aqrar_ext.api.get_item_price_history",
            args: { item_code: code, source: source, customer: customer },
            callback: function (r) {
                const data = r.message || {};
                const rows = data.history || [];
                const last_pr = data.last_price || 0;

                render_price_history_table(
                    d.fields_dict.history_table.$wrapper,
                    rows,
                    last_pr,
                    source
                );
            },
        });
    }

    d.fields_dict.item_code.$input.on("change", function () {
        load_table(d.fields_dict.item_code.get_value());
    });

    load_table(item_code);
}

function render_price_history_table($wrapper, rows, last_price, source) {

    source = source || "sales";
    const party_col = source === "purchase" ? __("Supplier") : __("Customer");
    const rate_col = source === "purchase" ? __("Purchase Rate") : __("Sales Rate (Txn)");
    const last_col = source === "purchase" ? __("Last Sales Rate") : __("Last Purchase Rate");
    const empty_msg = source === "purchase" ? __("No purchase history found") : __("No sales history found");

    if (!rows.length) {
        $wrapper.html(
            '<p class="text-muted">' + empty_msg + "</p>"
        );
        return;
    }

    let html = `
        <div class="price-history-table-wrap">
        <table class="table table-bordered table-condensed" style="margin:0;">
            <thead>
                <tr>
                    <th>${__("Item Code")}</th>
                    <th>${__("Item Name")}</th>
                    <th>${party_col}</th>
                    <th>${rate_col}</th>
                    <th>${__("Qty")}</th>
                    <th>${last_col}</th>
                </tr>
                <tr class="ph-filter-row">
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="0" placeholder="${__("Filter Item Code")}"></th>
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="1" placeholder="${__("Filter Item Name")}"></th>
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="2" placeholder="${__("Filter") + " " + party_col}"></th>
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="3" placeholder="${__("Filter Rate")}"></th>
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="4" placeholder="${__("Filter Qty")}"></th>
                    <th><input type="text" class="ph-filter form-control input-xs" data-col="5" placeholder="${__("Filter") + " " + last_col}"></th>
                </tr>
            </thead>
            <tbody class="ph-tbody">
    `;

    function build_row(r) {
        return `
            <tr>
                <td>${r.item_code}</td>
                <td>${r.item_name || ""}</td>
                <td>${r.party || r.customer || ""}</td>
                <td>${format_currency(r.rate)}</td>
                <td>${r.qty}</td>
                <td>${format_currency(last_price)}</td>
            </tr>
        `;
    }

    rows.forEach(function (r) {
        html += build_row(r);
    });

    html += `
            </tbody>
        </table>
        </div>
    `;

    $wrapper.html(html);

    // Filter logic
    var $table = $wrapper.find(".price-history-table-wrap");

    $table.on("input", ".ph-filter", function () {
        var filters = [];
        $table.find(".ph-filter").each(function () {
            filters.push($(this).val().toLowerCase().trim());
        });

        var tbody_html = "";
        var count = 0;

        rows.forEach(function (r) {
            var cols = [
                (r.item_code || "").toLowerCase(),
                (r.item_name || "").toLowerCase(),
                (r.party || r.customer || "").toLowerCase(),
                format_currency(r.rate).toLowerCase(),
                String(r.qty || 0).toLowerCase(),
                format_currency(last_price).toLowerCase(),
            ];

            var match = true;
            for (var i = 0; i < 6; i++) {
                if (filters[i] && cols[i].indexOf(filters[i]) === -1) {
                    match = false;
                    break;
                }
            }

            if (match) {
                tbody_html += build_row(r);
                count++;
            }
        });

        if (!count) {
            tbody_html = '<tr><td colspan="6" class="text-muted">' + __("No matching records") + "</td></tr>";
        }

        $table.find(".ph-tbody").html(tbody_html);
    });
}

function update_all_last_prices(frm, config) {

    if (frm.doc.docstatus !== 0) return;

    (frm.doc.items || []).forEach(row => {

        if (row.item_code) {
            update_row_last_price(frm, row, config);
        }
    });
}

function update_row_last_price(frm, row, config) {

    // Do not modify submitted/cancelled documents
    if (frm.doc.docstatus !== 0) return;

    const party = frm.doc[config.customer_field];

    frappe.call({
        method: "aqrar_ext.api.get_last_sold_price",
        args: {
            customer: party,
            item_code: row.item_code,
            source: config.source
        },
        callback: function(r) {

            if (!r.message) return;

            frappe.model.set_value(
                row.doctype,
                row.name,
                "custom_last_price",
                r.message.last_price || 0
            );
        }
    });
}

function show_price_popup(frm, row, config) {

    $(".customer-price-popup").remove();

    const party = frm.doc[config.customer_field];

    frappe.call({
        method: "aqrar_ext.api.get_item_insights",
        args: {
            customer: party,
            item_code: row.item_code,
            company: frm.doc.company,
            source: config.source
        },
        callback: function(r) {

            render_popup(frm, row, r.message || {});
        }
    });
}

function render_popup(frm, row, data) {

    $(".customer-price-popup").remove();

    row._popup_opened = true;

    const stock = data.stock || [];
    const history = data.price_history || [];
    const purchase_rate = data.last_purchase_rate || 0;

    let html = `
        <div class="customer-price-popup">

            <div class="cpp-header">
                <div class="cpp-title">
                    ${row.item_name || row.item_code}
                </div>

                <div class="cpp-close">
                    ✕
                </div>
            </div>

            <div class="cpp-section">

                <div class="cpp-subtitle">
                    Last Purchase Rate
                </div>

                <div class="cpp-rate">
                    ${purchase_rate}
                </div>

            </div>
    `;

    html += `
        <div class="cpp-section">

            <div class="cpp-subtitle">
                Stock By Warehouse
            </div>
    `;

    stock.forEach(s => {

        html += `
            <div class="cpp-line">
                <span>${s.warehouse}</span>
                <span>${s.projected_qty}</span>
            </div>
        `;
    });

    html += `</div>`;

    html += `
        <div class="cpp-section">

            <div class="cpp-subtitle">
                Customer Price History
            </div>
    `;

    history.forEach(h => {

        html += `
            <div class="cpp-history">

                <div>
                    <b>${format_currency(h.rate)}</b>
                </div>

                <div>
                    ${h.customer}
                </div>

                <div>
                    ${frappe.datetime.str_to_user(h.posting_date)}
                </div>

            </div>
        `;
    });

    html += `</div></div>`;

    const $popup = $(html).appendTo("body");

    const $row = $(`.grid-row[data-name="${row.name}"]`);

    if ($row.length) {

        const pos = $row.offset();
        const popup_h = 450;  // approximate popup height
        const popup_w = 430;
        const win_h = $(window).height();
        const win_w = $(window).width();

        let top = pos.top + 40;
        let left = pos.left + 250;

        // Clamp to viewport — flip above row if near bottom
        if (top + popup_h > win_h + $(window).scrollTop()) {
            top = pos.top - popup_h - 10;
        }
        if (left + popup_w > win_w) {
            left = win_w - popup_w - 20;
        }

        $popup.css({
            top: top,
            left: left
        });
    }

    $popup.find(".cpp-close").on("click", function () {

        $(".customer-price-popup").remove();

        row._popup_opened = false;
    });
}

// aqrar_ext: Simplified Sales Invoice for Branch Users
frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (!frappe.user.has_role("Branch User") || frappe.user.has_role("System Manager") || frappe.user.has_role("Stock Manager") || frm._branch_setup_done) return;
        frm._branch_setup_done = true;

        // Hide unnecessary fields
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
        ].forEach(function (f) { frm.set_df_property(f, "hidden", 1); });

        // Hide sections
        [
            "accounting_dimensions_section", "currency_and_price_list",
            "section_break_49", "taxes_section", "customer_po_details",
            "more_info", "sales_team_section_break", "section_break2",
            "edit_printing_settings", "more_information", "subscription_section",
        ].forEach(function (s) { frm.set_df_property(s, "hidden", 1); });

        // Hide tabs
        ["payments_tab", "contact_and_address_tab", "terms_tab", "more_info_tab"]
            .forEach(function (t) { frm.set_df_property(t, "hidden", 1); });

        // naming_series — force hide via DOM (set_only_once blocks set_df_property)
        frm.set_df_property("naming_series", "reqd", 0);
        frm.set_df_property("naming_series", "hidden", 1);
        $(frm.fields_dict.naming_series.wrapper).hide();

        // Company read-only
        frm.set_df_property("company", "read_only", 1);

        // Payment Mode required
        frm.set_df_property("custom_payment_mode", "reqd", 1);

        // Auto-fill cost_center from Branch Configuration
        if (!frm.doc.cost_center) {
            frappe.call({
                method: "aqrar_ext.api.branch_config.get_user_branch_defaults",
                callback: function (r) {
                    if (r.message && r.message.cost_center) {
                        frm.set_value("cost_center", r.message.cost_center);
                    }
                    if (r.message && r.message.warehouse && !frm.doc.set_warehouse) {
                        frm.set_value("set_warehouse", r.message.warehouse);
                    }
                },
            });
        }
    },
});

$(document).on("click", function(e) {

    if ($(e.target).closest(".customer-price-popup").length) return;

    if ($(e.target).closest(".grid-row").length) return;

    $(".customer-price-popup").remove();
});

$(`

<style>

.customer-price-popup{
    position:absolute;
    z-index:1000;
    width:430px;
    background:#111827;
    color:white;
    padding:16px;
    border-radius:14px;
    box-shadow:0 10px 30px rgba(0,0,0,.45);
}

.cpp-header{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:14px;
}

.cpp-title{
    font-size:18px;
    font-weight:700;
}

.cpp-close{
    cursor:pointer;
    font-size:16px;
    opacity:.7;
}

.cpp-close:hover{
    opacity:1;
}

.cpp-section{
    margin-bottom:20px;
}

.cpp-subtitle{
    font-size:11px;
    text-transform:uppercase;
    opacity:.7;
    margin-bottom:8px;
}

.cpp-line{
    display:flex;
    justify-content:space-between;
    padding:8px 0;
    border-bottom:1px solid rgba(255,255,255,.08);
}

.cpp-history{
    background:#1f2937;
    padding:10px;
    border-radius:10px;
    margin-bottom:8px;
}

.cpp-rate{
    font-size:24px;
    font-weight:bold;
    color:#22c55e;
}

.price-history-table-wrap{
    max-height:500px;
    overflow-y:auto;
}

.price-history-table-wrap table{
    font-size:12px;
}

.price-history-table-wrap thead tr:first-child th{
    position:sticky;
    top:0;
    background:#f8f9fa;
    z-index:2;
}

.price-history-table-wrap .ph-filter-row th{
    position:sticky;
    top:22px;
    background:#fff;
    z-index:2;
    padding:4px;
}

.ph-filter{
    font-size:11px;
    height:22px;
    padding:2px 6px;
}

</style>

`).appendTo("head");