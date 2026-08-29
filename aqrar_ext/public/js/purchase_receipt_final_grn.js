// CR-001 — Final GRN: restate the cost of stock that was received without a
// rate. A new Purchase Receipt carries the real rate; the original is then
// cancelled through a server endpoint that is allowed past the
// "stock already consumed" guard (see events/purchase_receipt.py).

frappe.ui.form.on("Purchase Receipt", {
    refresh: function (frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Final GRN"), function () {
                start_final_grn(frm);
            }, __("Create"));
        }
    },

    after_save: function (frm) {
        finalise_source_receipt(frm);
    },
});

function start_final_grn(frm) {
    if (!frm.doc.items || !frm.doc.items.length) {
        frappe.msgprint(__("No items found to carry forward."));
        return;
    }

    frappe.confirm(
        __(
            "Create a Final GRN from {0}? The original receipt is cancelled once the new one is saved.",
            [frm.doc.name]
        ),
        function () {
            // frappe.model.open_mapped_doc gives us ERPNext's own field mapping
            // instead of the hand-maintained copy this used to carry, so new
            // core fields keep working without another edit here.
            const source = {
                name: frm.doc.name,
                docstatus: frm.doc.docstatus,
                posting_date: frm.doc.posting_date,
                posting_time: frm.doc.posting_time,
            };
            frappe.model.with_doctype("Purchase Receipt", function () {
                const doc = frappe.model.copy_doc(frm.doc);
                doc.amended_from = null;
                doc.docstatus = 0;
                doc.set_posting_time = 1;
                (doc.items || []).forEach(function (row) {
                    row.received_qty = row.qty;
                    row.rejected_qty = 0;
                });
                doc._aqrar_final_grn_source = source;

                frappe.set_route("Form", "Purchase Receipt", doc.name).then(function () {
                    if (!cur_frm || cur_frm.doctype !== "Purchase Receipt") return;
                    cur_frm._aqrar_final_grn_source = source;
                    apply_posting_offset(cur_frm, source);
                    frappe.show_alert(
                        {
                            message: __("Carried forward from {0}. Save to replace it.", [source.name]),
                            indicator: "blue",
                        },
                        6
                    );
                });
            });
        }
    );
}

// The replacement must post just before the original so the valuation it
// restates is applied to the same stock.
function apply_posting_offset(frm, source) {
    if (!source.posting_date) return;

    const dateParts = String(source.posting_date).split("-").map(Number);
    const timeParts = String(source.posting_time || "00:00:00").split(".")[0].split(":").map(Number);

    const valid =
        dateParts.length === 3 &&
        timeParts.length === 3 &&
        dateParts.every(function (n) { return !isNaN(n); }) &&
        timeParts.every(function (n) { return !isNaN(n); });

    if (!valid) {
        console.error("Final GRN: unparseable source posting date/time", source);
        return;
    }

    const dt = new Date(
        dateParts[0], dateParts[1] - 1, dateParts[2],
        timeParts[0], timeParts[1], timeParts[2]
    );
    dt.setMinutes(dt.getMinutes() - 10);

    frm.set_value("set_posting_time", 1);
    frm.set_value(
        "posting_date",
        dt.getFullYear() + "-" +
            String(dt.getMonth() + 1).padStart(2, "0") + "-" +
            String(dt.getDate()).padStart(2, "0")
    );
    frm.set_value(
        "posting_time",
        String(dt.getHours()).padStart(2, "0") + ":" +
            String(dt.getMinutes()).padStart(2, "0") + ":" +
            String(dt.getSeconds()).padStart(2, "0")
    );
}

function finalise_source_receipt(frm) {
    const source = frm._aqrar_final_grn_source;
    if (!source || !source.name) return;

    // Clear first: after_save fires again on every later save, and the original
    // must only ever be retired once.
    frm._aqrar_final_grn_source = null;

    const method =
        source.docstatus === 1
            ? "aqrar_ext.events.purchase_receipt.cancel_for_final_grn"
            : "aqrar_ext.events.purchase_receipt.delete_draft_for_final_grn";

    frappe.call({
        method: method,
        args: { purchase_receipt: source.name, replacement: frm.doc.name },
        freeze: true,
        freeze_message: __("Replacing {0}...", [source.name]),
        callback: function (r) {
            if (r.exc) return;
            frappe.show_alert(
                {
                    message:
                        source.docstatus === 1
                            ? __("{0} cancelled and replaced.", [source.name])
                            : __("Draft {0} deleted.", [source.name]),
                    indicator: "green",
                },
                6
            );
        },
        error: function () {
            frappe.msgprint({
                title: __("Original Receipt Not Replaced"),
                message: __(
                    "{0} was saved, but {1} could not be retired. Handle it manually so the stock is not counted twice.",
                    [frm.doc.name, source.name]
                ),
                indicator: "red",
            });
        },
    });
}
