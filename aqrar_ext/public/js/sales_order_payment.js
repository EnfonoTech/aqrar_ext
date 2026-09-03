// aqrar_ext/public/js/sales_order_payment.js
//
// "Receive Payment" on a submitted Sales Order — the order-side twin of the
// invoice popup in sales_invoice_pos_total_popup.js. Ported from Steel Force's
// public/js/sales_order_payment.js and kept deliberately consistent with the
// invoice dialog already running here: one amount row per allowed mode of
// payment, cheque number/date asked for only when a cheque mode carries an
// amount, and the whole collection sent in a single call.
//
// The server (aqrar_ext/api/sales_order_payment.py) is the authority on what may
// be collected; everything here is convenience and early feedback.

frappe.ui.form.on("Sales Order", {
    refresh(frm) {
        if (frm.doc.docstatus !== 1) return;
        // The server refuses both, so offering the dialog on a Closed / On Hold
        // order would only collect keystrokes it is going to throw away.
        if (frm.doc.status === "Closed" || frm.doc.status === "On Hold") return;

        frm.add_custom_button(__("Receive Payment"), function () {
            aqrar_show_so_payment_popup(frm);
        }).addClass("btn-primary");
    },
});

function aqrar_so_precision(state) {
    const p = cint(state && state.precision);
    return p > 0 ? p : 2;
}

function aqrar_show_so_payment_popup(frm) {
    if (frappe.flags.aqrar_so_popup_showing) return;
    frappe.flags.aqrar_so_popup_showing = true;

    const release = () => { frappe.flags.aqrar_so_popup_showing = false; };

    frappe.call({
        method: "aqrar_ext.api.sales_order_payment.get_sales_order_payment_state",
        args: { sales_order: frm.doc.name },
        freeze: true,
        freeze_message: __("Loading payment modes..."),
        callback: function (r) {
            const state = r && r.message;
            if (!state) return release();

            if (flt(state.balance) <= 0) {
                release();
                frappe.msgprint({
                    title: __("Nothing to Collect"),
                    message: __("Order {0} is already fully paid in advance.", [frm.doc.name]),
                    indicator: "blue",
                });
                return;
            }

            const modes = state.modes || [];
            const pdc_modes = state.pdc_modes || [];
            if (!modes.length && !pdc_modes.length) {
                release();
                frappe.msgprint({
                    title: __("No Payment Modes"),
                    message: __(
                        "No mode of payment is configured for your branch on company {0}.",
                        [state.company]
                    ),
                    indicator: "red",
                });
                return;
            }
            aqrar_render_so_dialog(frm, state, release);
        },
        error: release,
    });
}

function aqrar_render_so_dialog(frm, state, release) {
    const precision = aqrar_so_precision(state);
    const modes = state.modes || [];
    const pdc_modes = state.pdc_modes || [];
    const all_modes = modes.concat(pdc_modes.filter((m) => modes.indexOf(m) === -1));
    const is_cheque_mode = (m) => pdc_modes.indexOf(m) !== -1;

    const fields = [
        {
            fieldtype: "HTML",
            fieldname: "summary",
            options: `
                <div style="padding:8px 0 12px 0;line-height:1.7">
                    <div><b>${__("Order Total")}:</b>
                        ${format_currency(state.grand_total, state.currency)}</div>
                    <div><b>${__("Already Advanced")}:</b>
                        ${format_currency(state.advance_paid, state.currency)}</div>
                    <div style="font-size:1.05em"><b>${__("Balance to Collect")}:</b>
                        <span style="color:var(--text-color)">
                        ${format_currency(state.balance, state.currency)}</span></div>
                </div>`,
        },
        { fieldtype: "Section Break", label: __("Amounts") },
    ];

    all_modes.forEach((mode, i) => {
        fields.push({
            fieldtype: "Currency",
            fieldname: `amt_${i}`,
            label: mode + (is_cheque_mode(mode) ? ` (${__("Cheque")})` : ""),
            default: 0,
            precision: precision,
            onchange: function () { recompute(); },
        });
        if (i % 2 === 0) fields.push({ fieldtype: "Column Break" });
    });

    fields.push(
        { fieldtype: "Section Break" },
        {
            // Drives depends_on for the cheque fields. A real (hidden) field is
            // required: names beginning "__" are stripped from the dialog doc, so
            // set_value on one silently does nothing and the fields never appear.
            fieldtype: "Check",
            fieldname: "has_cheque",
            label: "has_cheque",
            hidden: 1,
            default: 0,
        },
        {
            fieldtype: "Date",
            fieldname: "posting_date",
            label: __("Posting Date"),
            default: frappe.datetime.get_today(),
        },
        { fieldtype: "Column Break" },
        {
            fieldtype: "Data",
            fieldname: "cheque_no",
            label: __("Cheque No"),
            depends_on: "eval:doc.has_cheque",
        },
        {
            fieldtype: "Date",
            fieldname: "cheque_date",
            label: __("Cheque Date"),
            depends_on: "eval:doc.has_cheque",
        },
        { fieldtype: "Section Break" },
        { fieldtype: "HTML", fieldname: "totals" }
    );

    const dialog = new frappe.ui.Dialog({
        title: __("Receive Payment — {0}", [frm.doc.name]),
        size: "large",
        fields: fields,
        primary_action_label: __("Receive Payment"),
        primary_action: function (vals) { submit(vals); },
    });

    dialog.onhide = () => release();

    function collected() {
        const rows = [];
        all_modes.forEach((mode, i) => {
            const amt = flt(dialog.get_value(`amt_${i}`));
            if (amt > 0) rows.push({ mode_of_payment: mode, amount: amt });
        });
        return rows;
    }

    function recompute() {
        const rows = collected();
        const total = rows.reduce((s, r) => s + flt(r.amount), 0);
        const remaining = flt(state.balance) - total;
        const has_cheque = rows.some((r) => is_cheque_mode(r.mode_of_payment));

        // depends_on reads the dialog doc, so the flag has to live on it
        dialog.set_value("has_cheque", has_cheque ? 1 : 0);
        dialog.refresh();

        const over = remaining < -0.0001;
        dialog.fields_dict.totals.$wrapper.html(`
            <div style="padding:6px 0;line-height:1.8">
                <div><b>${__("Entered")}:</b> ${format_currency(total, state.currency)}</div>
                <div style="color:${over ? "var(--red-500)" : "var(--text-muted)"}">
                    <b>${over ? __("Over by") : __("Remaining")}:</b>
                    ${format_currency(Math.abs(remaining), state.currency)}
                </div>
                ${over
                    ? `<div style="color:var(--red-500)">${__(
                          "The total is more than the order balance."
                      )}</div>`
                    : ""}
            </div>`);
    }

    function submit(vals) {
        const rows = collected();
        if (!rows.length) {
            frappe.msgprint(__("Enter an amount against at least one mode of payment."));
            return;
        }
        const total = rows.reduce((s, r) => s + flt(r.amount), 0);
        if (total - flt(state.balance) > 0.0001) {
            frappe.msgprint(
                __("Total {0} is more than the balance of {1}.", [
                    format_currency(total, state.currency),
                    format_currency(state.balance, state.currency),
                ])
            );
            return;
        }
        const needs_cheque = rows.some((r) => is_cheque_mode(r.mode_of_payment));
        if (needs_cheque && !vals.cheque_no) {
            frappe.msgprint(__("Enter the cheque number."));
            return;
        }

        dialog.disable_primary_action();
        frappe.call({
            method: "aqrar_ext.api.sales_order_payment.create_payments_for_sales_order",
            args: {
                sales_order: frm.doc.name,
                payments: JSON.stringify(rows),
                cheque_no: vals.cheque_no || null,
                cheque_date: vals.cheque_date || null,
                posting_date: vals.posting_date || null,
            },
            freeze: true,
            freeze_message: __("Creating Payment Entries..."),
            callback: function (r) {
                const created = (r && r.message) || [];
                dialog.hide();
                frm.reload_doc();
                frappe.show_alert(
                    {
                        message: __("{0} Payment Entry(s) created: {1}", [
                            created.length,
                            created.join(", "),
                        ]),
                        indicator: "green",
                    },
                    7
                );
            },
            error: function () { dialog.enable_primary_action(); },
        });
    }

    dialog.show();
    recompute();
}
