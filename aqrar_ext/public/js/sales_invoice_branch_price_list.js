frappe.ui.form.on("Sales Invoice", {
    onload: function (frm) {
        if (frm.is_new()) auto_set_cost_center_price_list(frm);
    },
    customer: function (frm) {
        auto_set_cost_center_price_list(frm);
    },
    cost_center: function (frm) {
        auto_set_cost_center_price_list(frm);
    },
});

frappe.ui.form.on("Quotation", {
    onload: function (frm) {
        if (frm.is_new()) auto_set_cost_center_price_list(frm);
    },
    customer: function (frm) {
        auto_set_cost_center_price_list(frm);
    },
    cost_center: function (frm) {
        auto_set_cost_center_price_list(frm);
    },
});

/**
 * Find an enabled, selling Price List tagged with this cost center.
 * Uses the custom_branch field on Price List (which links to Cost Center).
 */
function get_cost_center_price_list(cost_center) {
    return new Promise(function (resolve) {
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Price List",
                filters: {
                    custom_branch: cost_center,
                    enabled: 1,
                    selling: 1,
                },
                fields: ["name"],
                limit: 1,
            },
            callback: function (r) {
                var pl = (r.message && r.message.length) ? r.message[0].name : null;
                resolve(pl);
            },
        });
    });
}

/**
 * Check a price list name exists and is enabled.
 */
function is_price_list_enabled(pl_name) {
    return new Promise(function (resolve) {
        if (!pl_name) return resolve(false);
        frappe.db.get_value("Price List", pl_name, "enabled", function (r) {
            resolve(!!(r && r.enabled));
        });
    });
}

/**
 * Auto-select the selling price list.
 *
 * Priority:
 *  1. Cost-center-specific Price List (if cost_center is set on the invoice)
 *  2. Customer default_price_list  (if set and enabled)
 *  3. Standard Selling             (global fallback)
 */
function auto_set_cost_center_price_list(frm) {
    if (!frm.doc.customer) return;
    if (frm.doc.docstatus !== 0) return;

    resolve_cost_center(frm).then(function (cost_center) {
        if (cost_center) {
            get_cost_center_price_list(cost_center).then(function (cc_pl) {
                if (cc_pl) {
                    set_price_list_if_changed(frm, cc_pl);
                } else {
                    set_from_customer_or_fallback(frm);
                }
            });
        } else {
            set_from_customer_or_fallback(frm);
        }
    });
}

function set_price_list_if_changed(frm, new_pl) {
    if (new_pl && frm.doc.selling_price_list !== new_pl) {
        frm.set_value("selling_price_list", new_pl);
    }
}

function set_from_customer_or_fallback(frm) {
    frappe.db.get_value("Customer", frm.doc.customer, "default_price_list", function (r) {
        var cust_pl = r && r.default_price_list ? r.default_price_list : null;
        is_price_list_enabled(cust_pl).then(function (ok) {
            if (ok) {
                set_price_list_if_changed(frm, cust_pl);
            } else {
                is_price_list_enabled("Standard Selling").then(function (std_ok) {
                    if (std_ok) set_price_list_if_changed(frm, "Standard Selling");
                });
            }
        });
    });
}

function resolve_cost_center(frm) {
    if (frm.doc.cost_center) {
        return Promise.resolve(frm.doc.cost_center);
    }
    // Fallback: user's default cost center from User Permission
    return new Promise(function (resolve) {
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "User Permission",
                filters: {
                    user: frappe.session.user,
                    allow: "Cost Center",
                    is_default: 1,
                },
                fields: ["for_value"],
                limit: 1,
            },
            callback: function (r) {
                var val = (r.message && r.message.length) ? r.message[0].for_value : null;
                resolve(val);
            },
        });
    });
}
