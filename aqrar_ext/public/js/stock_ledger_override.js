// aqrar_ext: Enhance Stock Ledger with Transaction Type + Item filter
(function () {
    var _report;

    // Delete any existing property so defineProperty works
    delete frappe.query_reports["Stock Ledger"];

    Object.defineProperty(frappe.query_reports, "Stock Ledger", {
        get: function () { return _report; },
        set: function (val) {
            if (val && val.filters && !val._aqrar) {
                val.filters.splice(1, 0, {
                    fieldname: "voucher_type",
                    label: __("Transaction Type"),
                    fieldtype: "Select",
                    options: ["All", "Purchase Only", "Sale Only", "Transfer Only", "Stock Entry Only"],
                    default: "All",
                });
                for (var i = 0; i < val.filters.length; i++) {
                    if (val.filters[i].fieldname === "item_code" && val.filters[i].fieldtype === "MultiSelectList") {
                        val.filters[i] = {
                            fieldname: "item_code",
                            label: __("Item"),
                            fieldtype: "Link",
                            options: "Item",
                        };
                        break;
                    }
                }
                val._aqrar = true;
            }
            _report = val;
        },
        configurable: true,
        enumerable: true,
    });
})();
