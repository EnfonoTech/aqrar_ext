// aqrar_ext: Enhance Stock Ledger with Transaction Type + Item filter
(function () {
    var _report;

    delete frappe.query_reports["Stock Ledger"];

    Object.defineProperty(frappe.query_reports, "Stock Ledger", {
        get: function () { return _report; },
        set: function (val) {
            if (val && val.filters && !val._aqrar) {
                // 1. Company filter — default to user's primary company
                for (var i = 0; i < val.filters.length; i++) {
                    if (val.filters[i].fieldname === "company") {
                        val.filters[i].default = frappe.defaults.get_user_default("Company")
                            || frappe.defaults.get_default("Company");
                        break;
                    }
                }

                // 2. Transaction Type filter
                val.filters.splice(1, 0, {
                    fieldname: "voucher_type",
                    label: __("Transaction Type"),
                    fieldtype: "Select",
                    options: ["All", "Purchase Only", "Sale Only", "Transfer Only", "Stock Entry Only"],
                    default: "All",
                });

                // 3. Item filter — single Link (item-wise default view)
                for (var j = 0; j < val.filters.length; j++) {
                    if (val.filters[j].fieldname === "item_code") {
                        val.filters[j] = {
                            fieldname: "item_code",
                            label: __("Item"),
                            fieldtype: "Link",
                            options: "Item",
                        };
                        break;
                    }
                }

                // 4. Point 19 — Special analysis hook
                // Custom per-client reports can be registered here:
                // aqrar_ext.stock_ledger_special_reports = [{label: "My Report", report_name: "..."}]
                if (!val.onload) val.onload = function () {};
                var _orig_onload = val.onload;
                val.onload = function (report) {
                    _orig_onload && _orig_onload(report);
                    _render_special_analysis_links(report);
                };

                val._aqrar = true;
            }
            _report = val;
        },
        configurable: true,
        enumerable: true,
    });

    function _render_special_analysis_links(report) {
        var custom_reports = (window.aqrar_ext || {}).stock_ledger_special_reports || [];
        if (!custom_reports.length) return;

        var $wrapper = $(report.wrapper).find(".page-form");
        if ($wrapper.find(".aqrar-special-analysis").length) return;

        var $links = $('<div class="aqrar-special-analysis" style="padding:8px 0 4px;">'
            + '<span style="font-weight:600;margin-right:8px;">' + __("Special Analysis:") + '</span>'
            + '</div>');

        custom_reports.forEach(function (r) {
            $links.append(
                $('<a class="btn btn-xs btn-default" style="margin-right:6px;">')
                    .text(__(r.label))
                    .on("click", function () {
                        frappe.set_route("query-report", r.report_name);
                    })
            );
        });

        $wrapper.append($links);
    }
})();
