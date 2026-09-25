// aqrar_ext: Wide "product search" style item picker with running search.
// Replaces the stock "Add Multiple" LinkSelector for item grids.

// Documents that take stock OUT — only these cap the quantity at what is on
// hand. On a purchase document a zero-stock item is exactly what you are buying.
const OUTGOING_DOCTYPES = ["Sales Invoice", "Delivery Note", "Sales Order", "Quotation"];

function aqrar_escape(value) {
    return frappe.utils.escape_html(String(value == null ? "" : value));
}

// CSS text-overflow:ellipsis on these flex columns proved unreliable across
// browsers/zoom levels — truncate the string itself instead, so the row
// height and column boundaries are never in question. Full text stays
// available via the title tooltip.
function aqrar_truncate(value, max_len) {
    var text = String(value == null ? "" : value);
    if (text.length <= max_len) return text;
    return text.slice(0, max_len - 1) + "…";
}

// Stays a Dialog (so the invoice form underneath is never left / unsaved
// changes are never at risk) but is stretched to fill almost the whole
// viewport, like a dedicated page.
function aqrar_inject_fullscreen_dialog_style() {
    if (document.getElementById("aqrar-item-selector-fullscreen-style")) return;
    $(
        '<style id="aqrar-item-selector-fullscreen-style">' +
            '.aqrar-fullscreen-dialog .modal-dialog {' +
                'width: 96vw; max-width: 96vw; height: 92vh; margin: 4vh auto;' +
            '}' +
            '.aqrar-fullscreen-dialog .modal-content {' +
                'height: 100%; display: flex; flex-direction: column;' +
            '}' +
            '.aqrar-fullscreen-dialog .modal-body {' +
                'flex: 1 1 auto; overflow-y: auto;' +
            '}' +
        '</style>'
    ).appendTo("head");
}

frappe.ui.form.ItemMultiSelector = class ItemMultiSelector {
    constructor(opts) {
        this.target = opts.target;          // the grid object
        this.item_field = opts.fieldname;   // typically "item_code"
        this.qty_field = opts.qty_fieldname; // typically "qty"
        this.uom_field = opts.uom_fieldname; // typically "uom", null if the child doctype has none
        this.get_query = opts.get_query;
        this.start = 0;
        this.page_length = 20;
        this.enforce_stock = OUTGOING_DOCTYPES.indexOf(
            (this.target && this.target.frm && this.target.frm.doctype) || ""
        ) !== -1;
        this.is_buying_doc = !cur_frm.doc.selling_price_list && !!cur_frm.doc.buying_price_list;
        this.price_list = cur_frm.doc.selling_price_list || cur_frm.doc.buying_price_list || "";
        this.make();
    }

    make() {
        var me = this;

        this.dialog = new frappe.ui.Dialog({
            title: __("Product Search"),
            size: "extra-large",
            fields: [
                {
                    fieldtype: "Link",
                    fieldname: "item_group",
                    label: __("Category"),
                    options: "Item Group",
                    onchange: function () {
                        me.start = 0;
                        me.search();
                    },
                },
                { fieldtype: "Column Break" },
                {
                    fieldtype: "Data",
                    fieldname: "item_name_txt",
                    label: __("Item Name"),
                    placeholder: __("Type to search..."),
                    onchange: function () {
                        me.debounced_search();
                    },
                },
                { fieldtype: "Column Break" },
                {
                    fieldtype: "Data",
                    fieldname: "item_code_txt",
                    label: __("Item Code"),
                    onchange: function () {
                        me.debounced_search();
                    },
                },
                { fieldtype: "Section Break" },
                {
                    fieldtype: "Link",
                    fieldname: "warehouse",
                    label: __("Warehouse"),
                    options: "Warehouse",
                    onchange: function () {
                        me.active_warehouse = me.dialog.fields_dict.warehouse.get_value() || "";
                        me.start = 0;
                        me.search();
                    },
                },
                { fieldtype: "Column Break" },
                {
                    fieldtype: "Float",
                    fieldname: "min_stock",
                    label: __("Min Stock"),
                    description: __("Hide items with less stock than this"),
                    onchange: function () {
                        me.apply_stock_filter();
                    },
                },
                { fieldtype: "Section Break" },
                {
                    fieldtype: "HTML",
                    fieldname: "results_area",
                },
            ],
        });

        aqrar_inject_fullscreen_dialog_style();
        this.dialog.$wrapper.addClass("aqrar-fullscreen-dialog");
        this.dialog.show();

        // "Added Items" bar + the search results live inside the same HTML
        // field, as separate children — render_results() only ever empties
        // the "search-results-container" child, so the bar survives re-search.
        this.dialog.fields_dict.results_area.$wrapper.html(
            '<div class="aqrar-added-items-bar" style="border:1px solid #d1d8dd; border-radius:4px; margin-bottom:10px;"></div>' +
            '<div class="search-results-container"></div>'
        );
        this.render_added_items();

        // Resolve warehouse, set on dialog, then load
        this._resolve_warehouse(function(warehouse) {
            me.active_warehouse = warehouse;
            if (warehouse) {
                me.dialog.fields_dict.warehouse.set_value(warehouse);
            }
            me.search();
        });
    }

    _resolve_warehouse(callback) {
        var me = this;
        var existing_items = cur_frm.doc[me.target.df.fieldname] || [];
        var first_item_wh  = (existing_items.find(function(d) { return d.warehouse; }) || {}).warehouse || "";
        var warehouse = cur_frm.doc.set_warehouse || cur_frm.doc.set_source_warehouse || first_item_wh || "";

        if (warehouse) {
            callback(warehouse);
        } else {
            frappe.call({
                method: "aqrar_ext.api.branch_config.get_user_branch_defaults",
                callback: function(r) {
                    callback((r.message && r.message.warehouse) || "");
                }
            });
        }
    }

    // Shows what's already in the invoice grid so far, right inside this
    // popup — refreshed after every "+" click.
    render_added_items() {
        var me = this;
        var $wrap = this.dialog.fields_dict.results_area.$wrapper.find(".aqrar-added-items-bar");
        var rows = (me.target.frm.doc[me.target.df.fieldname] || []).filter(function (d) {
            return d[me.item_field];
        });

        if (!rows.length) {
            $wrap.html(
                '<div style="padding:6px 4px; font-size:12px;">' +
                    '<b>' + __("Added Items") + ':</b> ' +
                    '<span class="text-muted">' + __("None yet") + '</span>' +
                '</div>'
            );
            return;
        }

        var chips = rows
            .map(function (d) {
                var label = aqrar_escape(d[me.item_field]);
                if (d.item_name && d.item_name !== d[me.item_field]) {
                    label += " - " + aqrar_escape(d.item_name);
                }
                label += " × " + aqrar_escape(d[me.qty_field] || 0);
                if (me.uom_field && d[me.uom_field]) {
                    label += " " + aqrar_escape(d[me.uom_field]);
                }
                return (
                    '<div style="padding:3px 4px; border-bottom:1px solid #f0f4f7;">' + label + "</div>"
                );
            })
            .join("");

        $wrap.html(
            '<div style="padding:6px 4px 2px; font-size:12px;">' +
                '<b>' + __("Added Items") + ' (' + rows.length + '):</b>' +
            '</div>' +
            '<div style="max-height:140px; overflow-y:auto; padding:0 4px 4px; font-size:12px;">' +
                chips +
            "</div>"
        );
    }

    debounced_search() {
        if (this._search_timeout) clearTimeout(this._search_timeout);
        var me = this;
        this._search_timeout = setTimeout(function () {
            me.start = 0;
            me.search();
        }, 300);
    }

    search() {
        var me = this;
        var txt = this.dialog.fields_dict.item_name_txt.get_value() || "";

        var args = {
            txt: txt,
            searchfield: "name",
            start: this.start,
            page_length: this.page_length,
        };

        // Apply custom query filters from the grid field
        if (
            this.target.is_grid &&
            this.target.fieldinfo &&
            this.target.fieldinfo[this.item_field] &&
            this.target.fieldinfo[this.item_field].get_query
        ) {
            $.extend(args, this.target.fieldinfo[this.item_field].get_query(cur_frm.doc));
        }

        // Category / Item Code — merge into whatever filters the grid query
        // set, rather than overwriting them.
        var extra_filters = {};
        var item_group = this.dialog.fields_dict.item_group.get_value();
        var item_code_txt = this.dialog.fields_dict.item_code_txt.get_value();

        if (item_group) extra_filters.item_group = item_group;
        if (item_code_txt) extra_filters.item_code = ["like", "%" + item_code_txt + "%"];

        if (Object.keys(extra_filters).length) {
            if (Array.isArray(args.filters)) {
                Object.keys(extra_filters).forEach(function (fieldname) {
                    var val = extra_filters[fieldname];
                    args.filters.push(
                        Array.isArray(val)
                            ? ["Item", fieldname, val[0], val[1]]
                            : ["Item", fieldname, "=", val]
                    );
                });
            } else {
                args.filters = $.extend({}, args.filters, extra_filters);
            }
        }

        frappe.link_search("Item", args, function (results) {
            me.render_results(results, args.start > 0);
        });
    }

    render_results(results, append) {
        var parent = this.dialog.fields_dict.results_area.$wrapper.find(".search-results-container");

        if (!append) {
            parent.empty();
        }

        if (!results.length && !append) {
            parent.html(
                '<p class="text-muted" style="padding: 15px;">' + __("No items found") + "</p>"
            );
            return;
        }

        // Remove old Load More button before adding new rows
        parent.find(".load-more").remove();

        // Column widths shift slightly when a UOM selector is shown (not every
        // child doctype has a "uom" field — e.g. Custom Quote Item doesn't).
        var w = this.uom_field
            ? { category: 12, item_name: 20, item_code: 14, stock: 12, price: 10, uom: 10, qty: 14, action: 8 }
            : { category: 14, item_name: 26, item_code: 16, stock: 12, price: 10, uom: 0, qty: 14, action: 8 };

        if (!append) {
            // Build table header
            var header = $(
                '<div class="item-selector-header" style="display:flex; font-weight:bold; padding:8px 4px; border-bottom:1px solid #d1d8dd;">' +
                    '<span style="width:' + w.category + '%;">' + __("Category") + '</span>' +
                    '<span style="width:' + w.item_name + '%;">' + __("Item Name") + '</span>' +
                    '<span style="width:' + w.item_code + '%;">' + __("Item Code") + '</span>' +
                    '<span style="width:' + w.stock + '%;">' + __("Stock") + '</span>' +
                    '<span style="width:' + w.price + '%;">' + (this.is_buying_doc ? __("Buying Price") : __("Selling Price")) + '</span>' +
                    (this.uom_field ? '<span style="width:' + w.uom + '%;">' + __("UOM") + '</span>' : '') +
                    '<span style="width:' + w.qty + '%;">' + __("Quantity") + '</span>' +
                    '<span style="width:' + w.action + '%;"></span>' +
                '</div>'
            ).appendTo(parent);
            var list = $('<div class="item-selector-rows"></div>').appendTo(parent);
        } else {
            // Append to existing row container
            var list = parent.find(".item-selector-rows");
        }
        var me = this;

        // Collect item codes for batch stock/detail lookup
        var item_codes = results.map(function (r) { return r[0]; });

        // Render each row
        results.forEach(function (r) {
            var item_code = r[0];
            var item_name = r[1] || "";
            // Item codes and names are user-entered master data — escape before
            // they reach the DOM or a quote breaks the markup / the selector.
            var code_attr = aqrar_escape(item_code);

            var row = $(
                '<div class="item-selector-row" data-item="' + code_attr + '"' +
                     ' style="display:flex; align-items:center; padding:8px 4px; border-bottom:1px solid #f0f4f7;">' +
                    '<span style="flex:0 0 ' + w.category + '%; max-width:' + w.category + '%; min-width:0;' +
                        ' overflow:hidden; white-space:nowrap; display:block; padding-right:6px; box-sizing:border-box;"' +
                        ' class="text-muted item-group-cell" data-item="' + code_attr + '">...</span>' +
                    '<span style="flex:0 0 ' + w.item_name + '%; max-width:' + w.item_name + '%; min-width:0;' +
                        ' overflow:hidden; white-space:nowrap; display:block; padding-right:6px; box-sizing:border-box;"' +
                        ' title="' + code_attr + ' - ' + aqrar_escape(item_name) + '">' + aqrar_escape(aqrar_truncate(item_name, 32)) + '</span>' +
                    '<span style="flex:0 0 ' + w.item_code + '%; max-width:' + w.item_code + '%; min-width:0;' +
                        ' overflow:hidden; white-space:nowrap; display:block; padding-right:6px; box-sizing:border-box;"' +
                        ' title="' + code_attr + '"><b>' + aqrar_escape(aqrar_truncate(item_code, 16)) + '</b></span>' +
                    '<span style="width:' + w.stock + '%;">' +
                        '<span class="stock-badge badge" data-item="' + code_attr + '">...</span>' +
                        '<br><small class="text-muted stock-wh-label" data-item="' + code_attr + '"></small>' +
                    '</span>' +
                    '<span style="width:' + w.price + '%;" class="price-cell" data-item="' + code_attr + '"></span>' +
                    (me.uom_field
                        ? '<span style="width:' + w.uom + '%;">' +
                            '<select class="item-uom form-control input-xs" data-item="' + code_attr + '"' +
                                ' style="width:90px; height:24px; padding:0 4px;"></select>' +
                          '</span>'
                        : '') +
                    '<span style="width:' + w.qty + '%;">' +
                        '<input type="number" class="item-qty form-control input-xs" data-item="' + code_attr + '"' +
                            ' value="1" min="0" step="any"' +
                            ' style="width:80px; height:24px;">' +
                    '</span>' +
                    '<span style="width:' + w.action + '%;">' +
                        '<button class="btn btn-xs btn-primary item-add-btn" data-item="' + code_attr + '"' +
                            ' title="' + __("Add") + '" style="border-radius:50%; width:24px; height:24px; padding:0;">' +
                            '+' +
                        '</button>' +
                    '</span>' +
                '</div>'
            ).appendTo(list);

            // jQuery attribute selectors break on embedded quotes; keep a direct
            // handle on the row instead of re-querying by item code.
            row.data("aqrar-item", item_code);

            // Qty change — clamp to available stock as the user types
            row.find(".item-qty").on("change input", function () {
                var val = parseFloat($(this).val()) || 0;
                var max = parseFloat($(this).attr("max"));
                if (me.enforce_stock && !isNaN(max) && val > max) {
                    $(this).val(max);
                    frappe.show_alert({ message: __("Qty cannot exceed available stock ({0})", [max]), indicator: "orange" }, 3);
                }
            });

            // "+" adds this single item straight into the grid and stays open
            // for the next pick — mirrors the reference "Product Search" page.
            row.find(".item-add-btn").on("click", function () {
                var code = row.data("aqrar-item");
                var qty_inp = row.find(".item-qty");
                var qty = parseFloat(qty_inp.val()) || 1;
                var max = parseFloat(qty_inp.attr("max"));
                if (me.enforce_stock && !isNaN(max) && qty > max) {
                    qty = max;
                    qty_inp.val(max);
                    frappe.show_alert({ message: __("Qty cannot exceed available stock ({0})", [max]), indicator: "orange" }, 3);
                }

                var uom = me.uom_field ? row.find(".item-uom").val() : null;

                var $btn = $(this).prop("disabled", true);
                me.add_row_to_grid(code, qty, uom).then(function () {
                    frappe.show_alert({ message: __("{0} added", [code]), indicator: "green" }, 2);
                    $btn.prop("disabled", false);
                    me.render_added_items();
                });
            });
        });

        // Load stock/category/price/UOM info for all items
        this.load_stock_info(item_codes);
        this.load_item_details(item_codes);
        if (this.uom_field) this.load_uom_info(item_codes);

        // Load More button
        if (results.length >= this.page_length) {
            $(
                '<button class="btn btn-xs btn-default load-more" style="margin-top:8px;">' +
                    __("Load More") +
                    "</button>"
            )
                .appendTo(parent)
                .on("click", function () {
                    me.start += me.page_length;
                    me.search();
                });
        }
    }

    load_item_details(item_codes) {
        // The "Item" search results column order depends on which custom
        // query the calling doctype set on item_code (see item_selector_hook.js
        // targets: Sales Invoice/Quotation/Purchase Invoice use erpnext's
        // item_query, Custom Quote falls back to the generic search_widget) —
        // each puts fields at a different index. Fetch details directly
        // instead of relying on result column position.
        if (!item_codes.length) return;
        var me = this;

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Item",
                fields: ["name", "item_group", "standard_rate"],
                filters: { name: ["in", item_codes] },
                limit_page_length: item_codes.length,
            },
            callback: function (r) {
                var item_map = {};
                (r.message || []).forEach(function (d) {
                    item_map[d.name] = d;
                });

                me.dialog.$wrapper.find(".item-selector-row").each(function () {
                    var $row = $(this);
                    var code = $row.data("aqrar-item");
                    var item = item_map[code] || {};
                    $row.find(".item-group-cell")
                        .text(aqrar_truncate(item.item_group || "", 18))
                        .attr("title", item.item_group || "");
                    if (item.standard_rate) {
                        $row.find(".price-cell").text(format_currency(item.standard_rate));
                    }
                });

                if (me.price_list) me._load_price_list_rates(item_codes);
            },
        });
    }

    load_uom_info(item_codes) {
        if (!item_codes.length) return;
        var me = this;

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Item",
                fields: ["name", "stock_uom"],
                filters: { name: ["in", item_codes] },
                limit_page_length: item_codes.length,
            },
            callback: function (r) {
                var stock_uom_map = {};
                (r.message || []).forEach(function (d) {
                    stock_uom_map[d.name] = d.stock_uom;
                });

                frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "UOM Conversion Detail",
                        parent: "Item",
                        fields: ["parent", "uom"],
                        filters: { parent: ["in", item_codes], parentfield: "uoms" },
                        limit_page_length: 0,
                    },
                    callback: function (cr) {
                        var uom_map = {};
                        item_codes.forEach(function (code) {
                            uom_map[code] = stock_uom_map[code] ? [stock_uom_map[code]] : [];
                        });
                        (cr.message || []).forEach(function (row) {
                            var list = uom_map[row.parent] || (uom_map[row.parent] = []);
                            if (list.indexOf(row.uom) === -1) list.push(row.uom);
                        });

                        me.dialog.$wrapper.find(".item-uom").each(function () {
                            var $select = $(this);
                            var code = $select.data("item");
                            var uoms = uom_map[code] && uom_map[code].length ? uom_map[code] : [stock_uom_map[code]];
                            $select.empty();
                            (uoms || []).forEach(function (uom) {
                                if (!uom) return;
                                $select.append($("<option></option>").val(uom).text(uom));
                            });
                            if (stock_uom_map[code]) $select.val(stock_uom_map[code]);
                        });
                    },
                });
            },
        });
    }

    _load_price_list_rates(item_codes) {
        var me = this;

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Item Price",
                fields: ["item_code", "price_list_rate"],
                filters: {
                    item_code: ["in", item_codes],
                    price_list: me.price_list,
                    selling: me.is_buying_doc ? 0 : 1,
                    buying: me.is_buying_doc ? 1 : 0,
                },
                limit_page_length: item_codes.length,
            },
            callback: function (r) {
                var price_map = {};
                (r.message || []).forEach(function (p) {
                    price_map[p.item_code] = p.price_list_rate;
                });

                me.dialog.$wrapper.find(".price-cell").each(function () {
                    var $cell = $(this);
                    var code = $cell.closest(".item-selector-row").data("aqrar-item");
                    if (price_map[code] !== undefined) {
                        $cell.text(format_currency(price_map[code]));
                    }
                });
            },
        });
    }

    load_stock_info(item_codes) {
        if (!item_codes.length) return;
        var me = this;
        me.stock_map = {};
        me._do_stock_fetch(item_codes, me.active_warehouse || "");
    }

    _do_stock_fetch(item_codes, warehouse) {
        var me = this;

        var filters = { item_code: ["in", item_codes] };
        if (warehouse) filters.warehouse = warehouse;

        // Shown in brackets under the stock number so it's always clear which
        // warehouse the count is from, default warehouse included.
        var warehouse_label = warehouse || __("All Warehouses");

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Bin",
                fields: ["item_code", "actual_qty"],
                filters: filters,
                limit_page_length: 500,
            },
            callback: function (r) {
                // Build a fresh map — sum across warehouses when no specific warehouse
                var fetched = {};
                (r.message || []).forEach(function(b) {
                    fetched[b.item_code] = (fetched[b.item_code] || 0) + (b.actual_qty || 0);
                });

                me.dialog.$wrapper.find(".item-selector-row").each(function () {
                    var $row    = $(this);
                    var code    = $row.data("aqrar-item");
                    var badge   = $row.find(".stock-badge");
                    var qty_inp = $row.find(".item-qty");
                    var stock   = flt(fetched[code]);

                    // CR-005: out-of-stock items stay selectable and are shown
                    // with a "0" badge — they must not be hidden or locked.
                    badge.text(stock)
                        .removeClass()
                        .addClass("stock-badge badge")
                        .toggleClass("badge-danger", stock <= 0);
                    $row.find(".stock-wh-label").text("(" + warehouse_label + ")");

                    if (me.enforce_stock && stock > 0) {
                        qty_inp.attr("max", stock);
                        if (flt(qty_inp.val()) > stock) {
                            qty_inp.val(stock);
                        }
                    } else {
                        qty_inp.removeAttr("max");
                    }

                    me.stock_map[code] = stock;
                });

                me.apply_stock_filter();
            },
        });
    }

    apply_stock_filter() {
        var me = this;
        var raw = this.dialog.fields_dict.min_stock.get_value();
        var threshold = parseFloat(raw);
        var has_threshold = raw !== "" && raw != null && !isNaN(threshold);
        var $rows = me.dialog.$wrapper.find(".item-selector-row");

        $rows.each(function () {
            var $row = $(this);
            var code = $row.data("aqrar-item");
            var stock = me.stock_map ? me.stock_map[code] : undefined;

            if (!has_threshold || stock === undefined) {
                $row.show();
            } else {
                $row.toggle(stock >= threshold);
            }
        });

        // Among the rows that pass the threshold, surface the best-stocked
        // ones first — not just "enough", but "most available" first. Moves
        // the actual row elements (not clones), so their click handlers stay
        // attached; hidden rows are pushed after so they don't interleave.
        if (has_threshold) {
            var $list = $rows.first().parent();
            var $visible_sorted = $rows.filter(":visible").sort(function (a, b) {
                var stock_a = (me.stock_map && me.stock_map[$(a).data("aqrar-item")]) || 0;
                var stock_b = (me.stock_map && me.stock_map[$(b).data("aqrar-item")]) || 0;
                return stock_b - stock_a;
            });
            var $hidden = $rows.filter(":hidden");

            $visible_sorted.each(function () { $list.append(this); });
            $hidden.each(function () { $list.append(this); });
        }
    }

    add_row_to_grid(item_code, qty, uom) {
        var me = this;
        return new Promise(function (resolve) {
            var rows = me.target.frm.doc[me.target.df.fieldname] || [];
            var existing = rows.find(function (d) {
                return d[me.item_field] === item_code;
            });

            if (existing) {
                frappe.model
                    .set_value(existing.doctype, existing.name, me.qty_field, (existing[me.qty_field] || 0) + qty)
                    .then(function () { resolve(); });
            } else {
                var empty_row = rows.find(function (d) { return !d[me.item_field]; });
                var d = empty_row || me.target.add_new_row();
                frappe.timeout(0.1).then(function () {
                    var item_args = {};
                    item_args[me.item_field] = item_code;
                    frappe.model.set_value(d.doctype, d.name, item_args).then(function () {
                        frappe.model.set_value(d.doctype, d.name, me.qty_field, qty).then(function () {
                            if (me.uom_field && uom) {
                                frappe.model.set_value(d.doctype, d.name, me.uom_field, uom).then(resolve);
                            } else {
                                resolve();
                            }
                        });
                    });
                });
            }
        });
    }
};
