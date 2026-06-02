// aqrar_ext: Multi-select item picker with running search and quantity
// Replaces the stock "Add Multiple" LinkSelector for item grids.

frappe.ui.form.ItemMultiSelector = class ItemMultiSelector {
    constructor(opts) {
        this.target = opts.target;          // the grid object
        this.item_field = opts.fieldname;   // typically "item_code"
        this.qty_field = opts.qty_fieldname; // typically "qty"
        this.get_query = opts.get_query;
        this.start = 0;
        this.page_length = 20;
        this.selected = {};  // { item_code: qty }
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
        this.search();
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

            var row = $(
                '<div class="item-selector-row" data-item="' + item_code + '"' +
                     ' style="display:flex; align-items:center; padding:8px 4px; border-bottom:1px solid #f0f4f7; cursor:pointer;">' +
                    '<span style="width:5%;">' +
                        '<input type="checkbox" class="item-check" data-item="' + item_code + '"' +
                            ' ' + checked_attr + '>' +
                    '</span>' +
                    '<span style="width:35%;"><b>' + item_code + '</b></span>' +
                    '<span style="width:30%;" class="text-muted">' + item_name + '</span>' +
                    '<span style="width:10%;">' +
                        '<span class="stock-badge badge" data-item="' + item_code + '">...</span>' +
                    '</span>' +
                    '<span style="width:20%;">' +
                        '<input type="number" class="item-qty form-control input-xs" data-item="' + item_code + '"' +
                            ' value="' + qty_val + '" min="0" step="1"' +
                            ' style="width:80px; height:24px;">' +
                    '</span>' +
                '</div>'
            ).appendTo(list);

            // Checkbox click
            row.find(".item-check").on("change", function () {
                var code = $(this).attr("data-item");
                if (this.checked) {
                    var qty = parseFloat(row.find(".item-qty").val()) || 1;
                    me.selected[code] = qty;
                } else {
                    delete me.selected[code];
                }
            });

            // Qty change
            row.find(".item-qty").on("change input", function () {
                var code = $(this).attr("data-item");
                var val = parseFloat($(this).val()) || 0;
                if (row.find(".item-check").is(":checked")) {
                    me.selected[code] = val;
                }
            });
        });

        // Load stock info for all items
        this.load_stock_info(item_codes);

        // Load More button
        if (results.length >= this.page_length) {
            var me = this;
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

        var warehouse = (
            cur_frm.doc.set_warehouse ||
            cur_frm.doc.set_source_warehouse ||
            ""
        );

        var filters = { item_code: ["in", item_codes] };
        if (warehouse) {
            filters.warehouse = warehouse;
        }

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Bin",
                fields: ["item_code", "actual_qty"],
                filters: filters,
                limit_page_length: 500,
            },
            callback: function (r) {
                if (!r.message) {
                    // API failed — show "--" for all items
                    item_codes.forEach(function (code) {
                        var badge = me.dialog.$wrapper.find('.stock-badge[data-item="' + code + '"]');
                        badge.text("--").removeClass().addClass("stock-badge badge");
                    });
                    return;
                }
                // Sum actual_qty per item_code (across warehouses when no filter)
                var stock_map = {};
                r.message.forEach(function (b) {
                    var code = b.item_code;
                    stock_map[code] = (stock_map[code] || 0) + (b.actual_qty || 0);
                });
                item_codes.forEach(function (code) {
                    var badge = me.dialog.$wrapper.find('.stock-badge[data-item="' + code + '"]');
                    if (stock_map[code] === undefined) {
                        badge.text("0").removeClass().addClass("stock-badge badge");
                    } else if (stock_map[code] <= 0) {
                        badge.text("0").removeClass().addClass("stock-badge badge");
                    } else {
                        badge.text(stock_map[code]).removeClass().addClass("stock-badge badge");
                    }
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
                __("Added {0} items", [to_add.length]),
                "green"
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
                var d = me.target.add_new_row();
                // Set item_code first so item details are fetched,
                // then set qty to prevent it being overwritten by item defaults
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
