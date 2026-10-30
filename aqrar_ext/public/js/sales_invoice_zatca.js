// ZATCA: a VAT customer's invoice needs the buyer's full national address to go
// as a Standard (B2B) tax invoice, and ksa_compliance refuses to submit it
// without one. Before submitting, when the address is incomplete, ask whether to
// send this invoice as Simplified instead (aqrar_ext.aqrar_ext.utils.zatca_simplified).
//
// Called from aqrar_save_submit (sales_invoice_pos_total_popup.js), which every
// Sales Invoice submit goes through: the payment popups take over before_submit
// and submit with frm.save("Submit"), which does not run before_submit again.

(function () {

const API = "aqrar_ext.aqrar_ext.utils.zatca_simplified.check_buyer_address";
const FLAG = "custom_send_as_simplified";

// Resolves true to go on with the submit, false to stop it.
window.aqrar_confirm_zatca_type = function (frm) {
    if (!frm.doc.customer || frm.doc.is_return || frm.doc[FLAG]) return Promise.resolve(true);

    return frappe.call({ method: API, args: { customer: frm.doc.customer } }).then((r) => {
        const missing = (r.message && r.message.missing) || [];
        if (!missing.length) return true;

        return new Promise((resolve) => {
            let answered = false;
            const answer = (ok) => {
                if (answered) return;
                answered = true;
                d.hide();
                resolve(ok);
            };
            const d = new frappe.ui.Dialog({
                title: __("National Address Missing"),
                fields: [{
                    fieldtype: "HTML",
                    options:
                        "<p>" + __("{0} has a VAT number, but their national address is incomplete. Missing:", [frappe.utils.escape_html(frm.doc.customer_name || frm.doc.customer)]) + "</p>" +
                        "<ul>" + missing.map((m) => "<li>" + frappe.utils.escape_html(m) + "</li>").join("") + "</ul>" +
                        "<p>" + __("ZATCA does not accept a standard (B2B) tax invoice without it. You can send this invoice as a <b>simplified</b> tax invoice instead; the customer then cannot claim its input VAT.") + "</p>",
                }],
                primary_action_label: __("Submit as Simplified"),
                primary_action() {
                    frm.doc[FLAG] = 1;
                    answer(true);
                },
                secondary_action_label: __("Cancel"),
                secondary_action() { answer(false); },
            });
            // Closing the dialog any other way stops the submit too.
            d.onhide = () => answer(false);
            d.show();
        });
    });
};

})();
