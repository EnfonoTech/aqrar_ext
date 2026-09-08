// Wrapped in an IIFE: app_include_js files are plain <script> tags sharing one
// global lexical scope, so a top-level `const` here would collide with the same
// name in another app_include_js file and kill this whole script. fateh_trading
// could declare these at top level because doctype_js is wrapped in
// `new Function(...)()` by Frappe, which gives it function scope.
(function () {
frappe.provide("aqrar_ext.price_assist");

// Configuration for supported doctypes
const DOCTYPE_CONFIG = {
    "Sales Invoice": {
        type: "sales",
        child_doctype: "Sales Invoice Item",
        customer_field: "customer"
    },
    "Delivery Note": {
        type: "sales",
        child_doctype: "Delivery Note Item",
        customer_field: "customer"
    },
    "Sales Order": {
        type: "sales",
        child_doctype: "Sales Order Item",
        customer_field: "customer"
    },
    "Quotation": {
        type: "sales",
        child_doctype: "Quotation Item",
        customer_field: "party_name"
    },
    "Purchase Invoice": {
        type: "purchase",
        child_doctype: "Purchase Invoice Item",
        party_field: "supplier"
    },
    "Purchase Receipt": {
        type: "purchase",
        child_doctype: "Purchase Receipt Item",
        party_field: "supplier"
    }
};

// Generic function to setup form handlers for a doctype
function setup_doctype_handlers(doctype, config) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            // Store config on the form for later access
            if (!frm.__aqrar_price_assist_config) {
                frm.__aqrar_price_assist_config = config;
            }
            
            if (!frm.__price_assist_row_bound) {
                const grid = frm.fields_dict.items.grid;
                frm.fields_dict.items.grid.wrapper.on("click", ".grid-row", function () {
                    const row_name = $(this).attr("data-name");
                    if (!row_name) return;

                    const row = locals[config.child_doctype]?.[row_name];
                    if (!row) return;

                    if (frm.__price_assist_row && frm.__price_assist_row !== row) {
                        aqrar_ext.price_assist.hide(frm.__price_assist_row);
                    }

                    frm.__price_assist_row = row;
                    if (row.item_code) {
                        frm._price_history_clicked_item_code = row.item_code;
                    }
                });
                // Track focused row for Price History default item (like sf_trading last selling rate)
                if (!grid.wrapper.data("price_history_focus_bound")) {
                    const update_focused_item = function (e) {
                        const $body = grid.wrapper.find(".grid-body");
                        if (!$body.length || !$body[0].contains(e.target)) return;
                        const $row = $(e.target).closest(".grid-row");
                        if (!$row.length) return;
                        const grid_row = $row.data("grid_row");
                        if (grid_row && grid_row.doc && grid_row.doc.item_code) {
                            frm._price_history_focused_item_code = grid_row.doc.item_code;
                        }
                    };
                    grid.wrapper[0].addEventListener("focusin", update_focused_item, true);
                    grid.wrapper[0].addEventListener("focusout", update_focused_item, true);
                    grid.wrapper.data("price_history_focus_bound", true);
                }
                frm.__price_assist_row_bound = true;
            }

            // Add both toolbar buttons through the supported grid API. Unlike the
            // old hand-built HTML + setTimeout approach, add_custom_button styles
            // and positions the button and keeps it across grid re-renders. It is
            // idempotent by label, so calling it on every refresh is safe.
            const grid = frm.fields_dict.items.grid;
            const cfg = frm.__aqrar_price_assist_config || DOCTYPE_CONFIG[frm.doctype] || { customer_field: "customer", type: "sales" };
            const is_purchase = cfg.type === "purchase";

            const hist_label = is_purchase ? __("Show Purchase History") : __("Show Price History");
            const history_btn = grid.add_custom_button(hist_label, () => {
                open_item_history_dialog(frm, get_default_item_for_price_history(frm), is_purchase);
            });

            const price_assist_btn = grid.add_custom_button(__("Price Assist"), () => {
                const row = frm.__price_assist_row;
                const party_field = cfg.party_field || cfg.customer_field || "customer";

                if (!row) {
                    frappe.msgprint(__("Please click an Item row first"));
                    return;
                }

                const party = frm.doc[party_field];
                if (!party || !row.item_code) {
                    frappe.msgprint((is_purchase ? __("Supplier") : __("Customer")) + " " + __("and Item Code are required"));
                    return;
                }

                if (is_purchase) {
                    aqrar_ext.price_assist.show_purchase(frm, row, cfg);
                } else {
                    aqrar_ext.price_assist.show(frm, row, cfg);
                }
            });

            // On sales documents, also offer the item's purchase history (a cost
            // reference while selling) as a separate button after "Show Price History".
            const purchase_history_btn = is_purchase ? null : grid.add_custom_button(__("Show Purchase History"), () => {
                open_item_history_dialog(frm, get_default_item_for_price_history(frm), true);
            });

            // Keep the native Add Row / Add Multiple buttons first; move our custom
            // buttons after them (add_custom_button prepends by default), in order:
            // Price Assist, Show Price History, [Show Purchase History].
            price_assist_btn.appendTo(grid.grid_buttons);
            history_btn.appendTo(grid.grid_buttons);
            if (purchase_history_btn) purchase_history_btn.appendTo(grid.grid_buttons);
        }
    });

    // Setup child doctype handlers
    const childHandlers = {
        rate(frm, cdt, cdn) {
            aqrar_ext.price_assist.updateHighlight(locals[cdt][cdn]);
        }
    };
    
    // Add remove event handler if it exists
    // The event name format is typically: {child_doctype_lowercase}_remove
    const removeEventName = config.child_doctype.toLowerCase().replace(/\s+/g, '_') + '_remove';
    childHandlers[removeEventName] = function(frm, cdt, cdn) {
        aqrar_ext.price_assist.hide(locals[cdt]?.[cdn]);
    };
    
    frappe.ui.form.on(config.child_doctype, childHandlers);
    
    // Also listen to items_remove on parent form as fallback
    frappe.ui.form.on(doctype, {
        items_remove(frm) {
            // Clear any open price assist popups when items are removed
            if (frm.__price_assist_row) {
                aqrar_ext.price_assist.hide(frm.__price_assist_row);
                frm.__price_assist_row = null;
            }
        }
    });
}

// Setup handlers for all supported doctypes
for (const [doctype, config] of Object.entries(DOCTYPE_CONFIG)) {
    setup_doctype_handlers(doctype, config);
}

// Cost for this row = the valuation rate of the warehouse the row is actually
// drawing from, not a company-wide blend. Falls back to the blended figure and
// then to the item's last purchase rate, so the tile is never blank when any of
// them is known. Both backend figures are still returned — nothing was removed.
function row_cost(row, insights) {
    const stock = insights.stock || [];
    const wh = row.warehouse || row.s_warehouse || null;

    if (wh) {
        const hit = stock.find(s => s.warehouse === wh);
        if (hit && flt(hit.valuation_rate)) {
            return { value: flt(hit.valuation_rate), label: "Cost @ " + wh, scoped: true };
        }
    }
    if (flt(insights.valuation_rate)) {
        return { value: flt(insights.valuation_rate), label: "Cost (all whs)", scoped: false };
    }
    return { value: flt(insights.last_purchase_rate), label: "Last Purchase", scoped: false };
}

$.extend(aqrar_ext.price_assist, {
    show(frm, row, config) {
        this.hide(row);
        
        // Get customer field name from config (defaults to 'customer' if not specified)
        const customerField = config?.customer_field || "customer";
        const customer = frm.doc[customerField];
        
        frappe.call({
            method: "aqrar_ext.api.item_insights.get_item_insights",
            args: {
                customer: customer,
                item_code: row.item_code,
                company: frm.doc.company,
                limit: 6,
                other_limit: 5
            },
            callback: r => {
                this.render(frm, row, r.message || {}, config);
            }
        });
    },

    render(frm, row, insights, config) {
        this.hide(row);

        const price_history = insights.price_history || [];
        const other_customers = insights.other_customers || [];
        const stock = insights.stock || [];

        const last_purchase_rate = flt(insights.last_purchase_rate || 0);
        const last_rate = flt(insights.last_rate || 0);
        const cost = row_cost(row, insights);

        const id = `si-price-assist-${row.name}`;
        const $box = $(`<div class="si-price-assist" id="${id}"></div>`).appendTo("body");

        // Get customer field name from config (defaults to 'customer' if not specified)
        const customerField = config?.customer_field || "customer";
        const customer = frm.doc[customerField];

        $box.append(`<div class="pa-customer">${customer}</div>`);
        $box.append(`<div class="pa-title">Price History: ${row.item_name || row.item_code}</div>`);

        const current_rate = flt(row.stock_uom_rate ?? row.rate);
        let diff_text = "", diff_class = "";

        if (current_rate && last_rate) {
            const diff_pct = ((current_rate - last_rate) / last_rate) * 100;
            const abs = Math.abs(diff_pct);
            diff_class = abs <= 5 ? "pa-price-good" : abs <= 20 ? "pa-price-warn" : "pa-price-bad";
            diff_text = `${diff_pct >= 0 ? "+" : ""}${diff_pct.toFixed(1)}% vs last price`;
        }

        $box.append(`
            <div class="pa-summary ${diff_class}">
                <div class="pa-summary-main">
                    <div><label>Last</label><span>${last_rate || "-"}</span></div>
                    <div><label>Last Purchase</label><span>${last_purchase_rate ? last_purchase_rate.toFixed(2) : "-"}</span></div>
                    <div><label>${cost.label}</label><span>${cost.value ? cost.value.toFixed(2) : "-"}</span></div>
                </div>
                <div class="pa-summary-warning">${diff_text}</div>
            </div>
        `);

        price_history.forEach(d => {
            const uom = d.uom || d.stock_uom || "";
            $box.append($(`
                <div class="pa-line">
                    <div class="pa-left">
                        <b>${d.rate}</b> (${d.currency}, ${uom})
                        <small>${d.qty} ${uom} • ${frappe.format(d.posting_date, "Date")}</small>
                        <small class="pa-inv">
                            <a href="/app/sales-invoice/${encodeURIComponent(d.si)}" target="_blank">${d.si}</a>
                        </small>
                    </div>
                    <button class="pa-use">Use</button>
                </div>
            `).data("rate", d.rate));
        });

        if (other_customers.length) {
            $box.append(`<div class="pa-section-title">Other customers paying</div>`);
            other_customers.forEach(d => {
                const uom = d.uom || d.stock_uom || "";
                $box.append($(`
                    <div class="pa-line pa-other">
                        <div class="pa-left">
                            <b>${d.rate}</b> (${d.currency}, ${uom})
                            <small>${d.customer_name || d.customer}</small>
                        </div>
                        <button class="pa-use">Use</button>
                    </div>
                `).data("rate", d.rate));
            });
        }

        if (stock.length) {
            $box.append(`<div class="pa-section-title">Stock by Warehouse</div>`);
            const maxQty = Math.max(...stock.map(s => flt(s.actual_qty))) || 1;

            stock.forEach(s => {
                const fill = Math.min(100, (flt(s.actual_qty) / maxQty) * 100);
                $box.append(`
                    <div class="ps-line">
                        <div class="ps-left">
                            <b>${s.warehouse}</b>
                            <small>${s.actual_qty} available${flt(s.valuation_rate) ? " @ " + flt(s.valuation_rate).toFixed(2) : ""}</small>
                        </div>
                        <div class="ps-bar-wrap">
                            <div class="ps-bar" style="width:${fill}%"></div>
                        </div>
                        <button class="ps-use">Use</button>
                    </div>
                `);
            });
        }

        const $input = $(`.grid-row[data-name="${row.name}"] input[data-fieldname="item_code"]`);
        if ($input.length) {
            const pos = $input.offset();
            $box.css({ top: pos.top + $input.outerHeight() + 8, left: pos.left });
        }

        $box.on("click", ".pa-use", function () {
            frappe.model.set_value(row.doctype, row.name, "rate", $(this).closest(".pa-line").data("rate"));
            frappe.model.set_value(row.doctype, row.name, "actual_rate", $(this).closest(".pa-line").data("rate"));
            aqrar_ext.price_assist.hide(row);
        });

        $box.on("click", ".ps-use", function () {
            frappe.model.set_value(row.doctype, row.name, "warehouse", $(this).closest(".ps-line").find("b").text());
        });

        row._price_id = id;
    },

    updateHighlight(row) {
        if (!row || !row._price_id) return;
        const rate = flt(row.stock_uom_rate ?? row.rate);
        $(`#${row._price_id} .pa-line`).each(function () {
            $(this).toggleClass("pa-match", flt($(this).data("rate")) === rate);
        });
    },

    hide(row) {
        if (row?._price_id) {
            $(`#${row._price_id}`).remove();
            delete row._price_id;
        }
    },

    show_purchase(frm, row, config) {
        this.hide(row);
        const supplier = frm.doc[config.party_field || "supplier"];
        frappe.call({
            method: "aqrar_ext.api.item_insights.get_item_purchase_insights",
            args: {
                supplier: supplier,
                item_code: row.item_code,
                company: frm.doc.company,
                limit: 6,
                other_limit: 5
            },
            callback: r => {
                this.render_purchase(frm, row, r.message || {}, config);
            }
        });
    },

    render_purchase(frm, row, insights, config) {
        this.hide(row);
        const price_history = insights.price_history || [];
        const other_suppliers = insights.other_customers || [];
        const stock = insights.stock || [];
        const last_purchase_rate = flt(insights.last_purchase_rate || 0);
        const last_rate = flt(insights.last_rate || 0);
        const valuation_rate = flt(insights.valuation_rate || 0);
        const cost = row_cost(row, insights);
        const id = `pi-price-assist-${row.name}`;
        const $box = $(`<div class="si-price-assist" id="${id}"></div>`).appendTo("body");
        const supplier = frm.doc[config.party_field || "supplier"];

        $box.append(`<div class="pa-customer">${supplier}</div>`);
        $box.append(`<div class="pa-title">Purchase Price: ${row.item_name || row.item_code}</div>`);

        const current_rate = flt(row.stock_uom_rate ?? row.rate);
        let diff_text = "", diff_class = "";
        if (current_rate && last_rate) {
            const diff_pct = ((current_rate - last_rate) / last_rate) * 100;
            const abs = Math.abs(diff_pct);
            diff_class = abs <= 5 ? "pa-price-good" : abs <= 20 ? "pa-price-warn" : "pa-price-bad";
            diff_text = `${diff_pct >= 0 ? "+" : ""}${diff_pct.toFixed(1)}% vs last purchase`;
        }

        $box.append(`
            <div class="pa-summary ${diff_class}">
                <div class="pa-summary-main">
                    <div><label>Last (Supplier)</label><span>${last_rate || "-"}</span></div>
                    <div><label>Valuation Rate</label><span>${valuation_rate ? valuation_rate.toFixed(2) : "-"}</span></div>
                    <div><label>${cost.label}</label><span>${cost.value ? cost.value.toFixed(2) : "-"}</span></div>
                </div>
                <div class="pa-summary-warning">${diff_text}</div>
            </div>
        `);

        price_history.forEach(d => {
            const doc_route = d.doctype === "Purchase Invoice" ? "purchase-invoice" : "purchase-receipt";
            const uom = d.uom || d.stock_uom || "";
            $box.append($(`
                <div class="pa-line">
                    <div class="pa-left">
                        <b>${d.rate}</b> (${d.currency}, ${uom})
                        <small>${d.qty} ${uom} • ${frappe.format(d.posting_date, "Date")}</small>
                        <small class="pa-inv">
                            <a href="/app/${doc_route}/${encodeURIComponent(d.doc_name)}" target="_blank">${d.doc_name}</a>
                        </small>
                    </div>
                    <button class="pa-use">Use</button>
                </div>
            `).data("rate", d.rate));
        });

        if (other_suppliers.length) {
            $box.append(`<div class="pa-section-title">Other suppliers</div>`);
            other_suppliers.forEach(d => {
                const uom = d.uom || d.stock_uom || "";
                $box.append($(`
                    <div class="pa-line pa-other">
                        <div class="pa-left">
                            <b>${d.rate}</b> (${d.currency}, ${uom})
                            <small>${d.supplier_name || d.customer_name || d.supplier || d.customer}</small>
                        </div>
                        <button class="pa-use">Use</button>
                    </div>
                `).data("rate", d.rate));
            });
        }

        if (stock.length) {
            $box.append(`<div class="pa-section-title">Stock by Warehouse</div>`);
            const maxQty = Math.max(...stock.map(s => flt(s.actual_qty))) || 1;
            stock.forEach(s => {
                const fill = Math.min(100, (flt(s.actual_qty) / maxQty) * 100);
                $box.append(`
                    <div class="ps-line">
                        <div class="ps-left">
                            <b>${s.warehouse}</b>
                            <small>${s.actual_qty} available${flt(s.valuation_rate) ? " @ " + flt(s.valuation_rate).toFixed(2) : ""}</small>
                        </div>
                        <div class="ps-bar-wrap">
                            <div class="ps-bar" style="width:${fill}%"></div>
                        </div>
                        <button class="ps-use">Use</button>
                    </div>
                `);
            });
        }

        const $input = $(`.grid-row[data-name="${row.name}"] input[data-fieldname="item_code"]`);
        if ($input.length) {
            const pos = $input.offset();
            $box.css({ top: pos.top + $input.outerHeight() + 8, left: pos.left });
        }

        $box.on("click", ".pa-use", function () {
            frappe.model.set_value(row.doctype, row.name, "rate", $(this).closest(".pa-line").data("rate"));
            frappe.model.set_value(row.doctype, row.name, "actual_rate", $(this).closest(".pa-line").data("rate"));
            aqrar_ext.price_assist.hide(row);
        });
        $box.on("click", ".ps-use", function () {
            frappe.model.set_value(row.doctype, row.name, "warehouse", $(this).closest(".ps-line").find("b").text());
        });

        row._price_id = id;
    }
});

$(document).on("click.price_assist", function (e) {
    if ($(e.target).closest(".si-price-assist").length) return;
    if ($(e.target).closest(".grid-row").length) return;

    const frm = cur_frm;
    if (frm?.__price_assist_row) {
        aqrar_ext.price_assist.hide(frm.__price_assist_row);
    }
});

// Get default item for Price History dialog: last clicked/focused row, or last row (like sf_trading last selling rate)
function get_default_item_for_price_history(frm) {
    if (!frm || !frm.fields_dict.items || !frm.fields_dict.items.grid) {
        return null;
    }
    const items_grid = frm.fields_dict.items.grid;

    // 1. Prefer the row that is currently open/expanded
    const open_row = frappe.ui.form.get_open_grid_form();
    if (open_row && open_row.grid === items_grid && open_row.doc && open_row.doc.item_code) {
        return open_row.doc.item_code;
    }
    // 2. Else the row that last had focus
    if (frm._price_history_focused_item_code) {
        return frm._price_history_focused_item_code;
    }
    // 3. Else the last clicked row in the items grid
    if (frm._price_history_clicked_item_code) {
        return frm._price_history_clicked_item_code;
    }
    // 4. Fallback: last row's item in the items table
    if (frm.doc.items && frm.doc.items.length) {
        const last_row = frm.doc.items[frm.doc.items.length - 1];
        if (last_row && last_row.item_code) {
            return last_row.item_code;
        }
    }
    return null;
}

function open_item_history_dialog(frm, default_item_code, is_purchase) {
    const title = is_purchase ? 'Item Purchase Price History' : 'Item Sales & Purchase Price History';
    // Scope the list to this document's branch. Quotation has no cost_center
    // field at all, so this is undefined there and the server returns all
    // branches rather than an unexplained empty table.
    const cost_center = frm.doc.cost_center || null;
    let d = new frappe.ui.Dialog({
      title: title,
      fields: [
        { fieldname: 'item_code', label: 'Item Code', fieldtype: 'Link', options: 'Item', default: default_item_code },
        { fieldname: 'results', fieldtype: 'HTML' }
      ],
      size: 'extra-large',
      primary_action_label: 'Close',
      primary_action: function () {
        d.hide();
      }
    });
  
    d.show();
  
    setTimeout(() => {
      if (d.fields_dict.item_code) {
        d.fields_dict.item_code.df.onchange = function () {
          const item_code = d.get_value('item_code');
          if (item_code) {
            fetch_item_history(item_code, 20, d, is_purchase, cost_center);
          }
        };
      }
  
      if (default_item_code) {
        fetch_item_history(default_item_code, 20, d, is_purchase, cost_center);
      }
    }, 200);
  }
  
  function fetch_item_history(item_code, limit, dialog, is_purchase, cost_center) {
    dialog.fields_dict.results.$wrapper.html('<div class="text-muted">Loading…</div>');
  
    const method = is_purchase ? 'aqrar_ext.api.item_insights.get_item_purchase_history' : 'aqrar_ext.api.item_insights.get_item_sales_history';
    frappe.call({
      method: method,
      args: { item_code, limit, cost_center },
      callback: function (r) {
        const rows = r.message || [];
        if (!rows.length) {
          dialog.fields_dict.results.$wrapper.html('<div class="text-muted">No history found.</div>');
          return;
        }
  
        const html = is_purchase ? render_purchase_history_table(rows) : render_history_table(rows);
        dialog.fields_dict.results.$wrapper.html(html);

        dialog.fields_dict.results.$wrapper.find('[data-doctype][data-name]').on('click', function () {
          frappe.set_route('Form', this.getAttribute('data-doctype'), this.getAttribute('data-name'));
        });

        setTimeout(() => {
          setupTableFilters(dialog, is_purchase);
        }, 100);
      },
      error: function (err) {
        dialog.fields_dict.results.$wrapper.html('<div class="text-danger">Error fetching data: ' + err.message + '</div>');
      }
    });
  }
  
  function render_history_table(rows) {
    var out = [
      '<div class="mt-3">',
      '<table class="table table-bordered table-sm" id="price-history-table">',
      '<thead>',
      '<tr>',
      '<th>Item Code</th>',
      '<th>Item Name</th>',
      '<th>Customer</th>',
      '<th>Sales Rate</th>',
      '<th>Sales Qty</th>',
      '<th>Last Purchase Rate</th>',
      '</tr>',
      '<tr class="filter-row">',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Item Code"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Item Name"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Customer"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Sales Rate"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Sales Qty"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Purchase Rate"></th>',
      '</tr>',
      '</thead>',
      '<tbody>'
    ].join('');
  
    rows.forEach(function (r) {
      var item_code = frappe.utils.escape_html(r.item_code || '');
      var item_name = frappe.utils.escape_html(r.item_name || '');
      var cust = frappe.utils.escape_html(r.customer_name || r.customer || '');
      out += [
        '<tr>',
        `<td>${item_code}</td>`,
        `<td>${item_name}</td>`,
        `<td>${cust}</td>`,
        `<td class="text-right">${format_currency(r.stock_uom_rate || 0, r.currency || '')}</td>`,
        `<td class="text-right">${format_number(r.stock_qty ?? r.qty ?? 0, null)}</td>`,
        `<td class="text-right">${format_currency(r.last_purchase_rate || 0, r.currency || '')}</td>`,
        '</tr>'
      ].join('');
    });
  
    out += '</tbody></table></div>';
    return out;
  }

  function render_purchase_history_table(rows) {
    var out = [
      '<div class="mt-3">',
      '<table class="table table-bordered table-sm" id="price-history-table">',
      '<thead>',
      '<tr>',
      '<th>Item Code</th>',
      '<th>Item Name</th>',
      '<th>Supplier</th>',
      '<th>Purchase Rate</th>',
      '<th>Qty</th>',
      '<th>Last Selling Rate</th>',
      '<th>Document</th>',
      '</tr>',
      '<tr class="filter-row">',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Item Code"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Item Name"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Supplier"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Rate"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Qty"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Last Selling"></th>',
      '<th><input type="text" class="form-control input-sm" placeholder="Filter Document"></th>',
      '</tr>',
      '</thead>',
      '<tbody>'
    ].join('');

    rows.forEach(function (r) {
      var item_code = frappe.utils.escape_html(r.item_code || '');
      var item_name = frappe.utils.escape_html(r.item_name || '');
      var supp = frappe.utils.escape_html(r.supplier_name || r.supplier || '');
      var doc_name = frappe.utils.escape_html(r.doc_name || '');
      var doctype = r.doctype || 'Purchase Invoice';
      out += [
        '<tr>',
        `<td>${item_code}</td>`,
        `<td>${item_name}</td>`,
        `<td>${supp}</td>`,
        `<td class="text-right">${format_currency(r.stock_uom_rate ?? r.purchase_rate ?? 0, r.currency || '')}</td>`,
        `<td class="text-right">${format_number(r.stock_qty ?? r.qty ?? 0, null)}</td>`,
        `<td class="text-right">${format_currency(r.last_selling_rate || 0, r.currency || '')}</td>`,
        `<td><a href="#" data-doctype="${doctype}" data-name="${doc_name}">${doc_name}</a></td>`,
        '</tr>'
      ].join('');
    });

    out += '</tbody></table></div>';
    return out;
  }
  
  function setupTableFilters(dialog, is_purchase) {
    const table = dialog.fields_dict.results.$wrapper.find('#price-history-table')[0];
    if (!table) return;

    const filterInputs = table.querySelectorAll('.filter-row input');
    const tbody = table.querySelector('tbody');
    if (!tbody || !filterInputs.length) return;

    // remove old handlers
    filterInputs.forEach(input => {
      if (input._filterHandler) {
        input.removeEventListener('input', input._filterHandler);
        delete input._filterHandler;
      }
    });

    // attach new ones
    filterInputs.forEach((input, index) => {
      input._filterHandler = function () {
        applyAllFilters(dialog);
      };
      input.addEventListener('input', input._filterHandler);
    });
  }
  
  function applyAllFilters(dialog) {
    // Use dialog wrapper to scope the search
    const table = dialog.fields_dict.results.$wrapper.find('#price-history-table')[0];
    if (!table) return;

    const rows = table.querySelectorAll('tbody tr');
    const filterInputs = table.querySelectorAll('.filter-row input');

    rows.forEach(row => {
      let shouldShow = true;

      filterInputs.forEach((input, j) => {
        const val = input.value.toLowerCase().trim();
        if (!val) return;

        const cell = row.cells[j];
        if (cell) {
          const cellText = (cell.textContent || '').toLowerCase();
          if (cellText.indexOf(val) === -1) {
            shouldShow = false;
          }
        }
      });

      row.style.display = shouldShow ? '' : 'none';
    });
  }


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
.pa-line.pa-other{opacity:.85}
.pa-line.pa-match{border-color:rgba(0,230,118,.4)}
.pa-inv a{color:#58a6ff;text-decoration:none}
.pa-left b{font-size:14px;font-weight:600}
.pa-left small{display:block;font-size:10px;opacity:.75}
.pa-use{padding:6px 14px;font-size:11px;border-radius:8px;border:none;background:linear-gradient(90deg,#00d2ff,#3a7bd5);color:#fff;font-weight:600;cursor:pointer}
.ps-line{padding:8px;margin-bottom:6px;background:#101820;border-radius:10px;display:flex;align-items:center;gap:8px;border:1px solid rgba(255,255,255,.06)}
.ps-left{min-width:120px}
.ps-left small{font-size:10px;opacity:.75}
.ps-bar-wrap{flex:1;height:6px;background:rgba(255,255,255,.06);border-radius:999px;overflow:hidden}
.ps-bar{height:6px;border-radius:999px;background:linear-gradient(90deg,#00e676,#00b0ff)}
.ps-use{padding:4px 10px;font-size:10px;border-radius:999px;border:none;background:#263238;color:#e0f7fa;cursor:pointer}
</style>`).appendTo("head");


})();
