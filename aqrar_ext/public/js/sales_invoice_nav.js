// CR-022: previous / next navigation on the Sales Invoice form, following the
// list view's current filters and sort order.

frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (frm.is_new()) return;

        frm.page.add_action_icon("left", function () {
            navigate(frm, -1);
        }, "", __("Previous Invoice"));

        frm.page.add_action_icon("right", function () {
            navigate(frm, 1);
        }, "", __("Next Invoice"));
    },
});

function navigate(frm, direction) {
    const list_view = frappe.views.list_view && frappe.views.list_view["Sales Invoice"];
    const order_by = (list_view && list_view.sort_selector)
        ? list_view.sort_selector.sort_by + " " + list_view.sort_selector.sort_order
        : "modified desc";

    const filters = (list_view && list_view.get_filters_for_args)
        ? list_view.get_filters_for_args()
        : [];

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Sales Invoice",
            filters: filters,
            fields: ["name"],
            order_by: order_by,
            // Bounded on purpose: an unbounded fetch would pull the whole
            // invoice table just to find one neighbour.
            limit_page_length: 500,
        },
        callback: function (r) {
            const names = (r.message || []).map(function (d) { return d.name; });
            const index = names.indexOf(frm.doc.name);

            if (index === -1) {
                frappe.show_alert(
                    { message: __("This invoice is not in the current list view."), indicator: "orange" },
                    4
                );
                return;
            }

            const target = index + direction;
            if (target < 0 || target >= names.length) {
                frappe.show_alert(
                    {
                        message: direction < 0
                            ? __("Already at the first invoice.")
                            : __("Already at the last invoice."),
                        indicator: "blue",
                    },
                    4
                );
                return;
            }

            frappe.set_route("Form", "Sales Invoice", names[target]);
        },
    });
}
