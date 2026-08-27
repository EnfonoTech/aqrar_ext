// aqrar_ext: Multi-select item picker with running search and quantity
// Replaces the stock "Add Multiple" LinkSelector for item grids.

// Documents that take stock OUT — only these cap the quantity at what is on
// hand. On a purchase document a zero-stock item is exactly what you are buying.
const OUTGOING_DOCTYPES = ["Sales Invoice", "Delivery Note", "Sales Order", "Quotation"];

function aqrar_escape(value) {
    return frappe.utils.escape_html(String(value == null ? "" : value));
}

frappe.ui.form.ItemMultiSelector = class ItemMultiSelector {
    constructor(opts) {
        this.target = opts.target;          // the grid object
        this.item_field = opts.fieldname;   // typically "item_code"
        this.qty_field = opts.qty_fieldname; // typically "qty"
        this.get_query = opts.get_query;
        this.start = 0;
        this.page_length = 20;
        this.selected = {};  // { item_code: qty }
        this.enforce_stock = OUTGOING_DOCTYPES.indexOf(
            (this.target && this.target.frm && this.target.frm.doctype) || ""
        ) !== -1;
        this.make();
    }

    make() {
        var me = this;

        this.dialog = new frappe.ui.Dialog({
            title: __("Select Items"),
            fields: [
                {
                    fieldtype: "Data",
                    fieldname: "search_txt",
                    label: __("Search Items"),
                    placeholder: __("Type to search..."),
                    onchange: function () {
                        me.debounced_search();
                    },
                },
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
                {
                    fieldtype: "HTML",
                    fieldname: "results_area",
                },
            ],
            primary_action_label: __("Add Selected Items"),
            primary_action: function () {
                me.add_selected_to_grid();
            },
        });

        this.dialog.show();

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
        var txt = this.dialog.fields_dict.search_txt.get_value() || "";

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

        frappe.link_search("Item", args, function (results) {
            me.render_results(results, args.start > 0);
        });
    }

    render_results(results, append) {
        var parent = this.dialog.fields_dict.results_area.$wrapper;

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

        if (!append) {
            // Build table header
            var header = $(
                '<div class="item-selector-header" style="display:flex; font-weight:bold; padding:8px 4px; border-bottom:1px solid #d1d8dd;">' +
                    '<span style="width:5%;"></span>' +
                    '<span style="width:35%;">' + __("Item") + '</span>' +
                    '<span style="width:30%;">' + __("Description") + '</span>' +
                    '<span style="width:10%;">' + __("Stock") + '</span>' +
                    '<span style="width:20%;">' + __("Qty") + '</span>' +
                '</div>'
            ).appendTo(parent);
            var list = $('<div class="item-selector-rows"></div>').appendTo(parent);
        } else {
            // Append to existing row container
            var list = parent.find(".item-selector-rows");
        }
        var me = this;

        // Collect item codes for batch stock lookup
        var item_codes = results.map(function (r) { return r[0]; });

        // Render each row
        results.forEach(function (r) {
            var item_code = r[0];
            var item_name = r[1] || "";
            var checked_attr = me.selected[item_code] !== undefined ? "checked" : "";
            var qty_val = me.selected[item_code] || 1;
            // Item codes and names are user-entered master data — escape before
            // they reach the DOM or a quote breaks the markup / the selector.
            var code_attr = aqrar_escape(item_code);

            var row = $(
                '<div class="item-selector-row" data-item="' + code_attr + '"' +
                     ' style="display:flex; align-items:center; padding:8px 4px; border-bottom:1px solid #f0f4f7; cursor:pointer;">' +
                    '<span style="width:5%;">' +
                        '<input type="checkbox" class="item-check" data-item="' + code_attr + '"' +
                            ' ' + checked_attr + '>' +
                    '</span>' +
                    '<span style="width:35%;"><b>' + aqrar_escape(item_code) + '</b></span>' +
                    '<span style="width:30%;" class="text-muted">' + aqrar_escape(item_name) + '</span>' +
                    '<span style="width:10%;">' +
                        '<span class="stock-badge badge" data-item="' + code_attr + '">...</span>' +
                    '</span>' +
                    '<span style="width:20%;">' +
                        '<input type="number" class="item-qty form-control input-xs" data-item="' + code_attr + '"' +
                            ' value="' + aqrar_escape(qty_val) + '" min="0" step="any"' +
                            ' style="width:80px; height:24px;">' +
                    '</span>' +
                '</div>'
            ).appendTo(list);

            // jQuery attribute selectors break on embedded quotes; keep a direct
            // handle on the row instead of re-querying by item code.
            row.data("aqrar-item", item_code);

            // Checkbox click
            row.find(".item-check").on("change", function () {
                var code = row.data("aqrar-item");
                if (this.checked) {
                    var qty = parseFloat(row.find(".item-qty").val()) || 1;
                    me.selected[code] = qty;
                } else {
                    delete me.selected[code];
                }
            });

            // Qty change
            row.find(".item-qty").on("change input", function () {
                var code  = row.data("aqrar-item");
                var val   = parseFloat($(this).val()) || 0;
                var max   = parseFloat($(this).attr("max"));
                if (me.enforce_stock && !isNaN(max) && val > max) {
                    val = max;
                    $(this).val(max);
                    frappe.show_alert({ message: __("Qty cannot exceed available stock ({0})", [max]), indicator: "orange" }, 3);
                }
                if (row.find(".item-check").is(":checked")) {
                    me.selected[code] = val;
                }
            });
        });

        // Load stock info for all items
        this.load_stock_info(item_codes);

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

                    if (me.enforce_stock && stock > 0) {
                        qty_inp.attr("max", stock);
                        if (flt(qty_inp.val()) > stock) {
                            qty_inp.val(stock);
                            if (me.selected[code] !== undefined) me.selected[code] = stock;
                        }
                    } else {
                        qty_inp.removeAttr("max");
                    }

                    me.stock_map[code] = stock;
                });
            },
        });
    }

    add_selected_to_grid() {
        var me = this;
        var items = Object.keys(this.selected);

        if (!items.length) {
            frappe.msgprint(__("Please select at least one item."));
            return;
        }

        // Build list of rows to add
        var to_add = items
            .filter(function (code) {
                return (me.selected[code] || 0) > 0;
            })
            .map(function (code) {
                return { item_code: code, qty: me.selected[code] };
            });

        if (!to_add.length) {
            frappe.msgprint(__("All selected items have qty 0."));
            return;
        }

        // Pre-collect empty rows before async adds begin
        me._empty_rows_to_fill = (me.target.frm.doc[me.target.df.fieldname] || [])
            .filter(function (d) { return !d[me.item_field]; });

        // Add rows sequentially
        var chain = Promise.resolve();
        to_add.forEach(function (row) {
            chain = chain.then(function () {
                return me.add_row_to_grid(row.item_code, row.qty);
            });
        });

        chain.then(function () {
            me.dialog.hide();
            frappe.show_alert(
                { message: __("Added {0} items", [to_add.length]), indicator: "green" },
                5
            );
        });
    }

    add_row_to_grid(item_code, qty) {
        var me = this;
        return new Promise(function (resolve) {
            var existing = (me.target.frm.doc[me.target.df.fieldname] || []).find(function (d) {
                return d[me.item_field] === item_code;
            });

            if (existing) {
                frappe.model
                    .set_value(existing.doctype, existing.name, me.qty_field, qty)
                    .then(function () { resolve(); });
            } else {
                // Use pre-collected empty row if available, otherwise add new
                var empty_row = me._empty_rows_to_fill && me._empty_rows_to_fill.shift();
                var d = empty_row || me.target.add_new_row();
                frappe.timeout(0.1).then(function () {
                    var item_args = {};
                    item_args[me.item_field] = item_code;
                    frappe.model.set_value(d.doctype, d.name, item_args).then(function () {
                        frappe.model.set_value(d.doctype, d.name, me.qty_field, qty).then(function () {
                            resolve();
                        });
                    });
                });
            }
        });
    }
};
