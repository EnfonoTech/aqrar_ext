// ZATCA: a VAT customer's invoice needs the buyer's full national address to go
// as a Standard (B2B) tax invoice, and ksa_compliance refuses to submit it
// without one. On submit, when the address is incomplete, ask whether to send
// this invoice as Simplified instead (aqrar_ext.aqrar_ext.utils.zatca_simplified).

(function () {

const API = "aqrar_ext.aqrar_ext.utils.zatca_simplified.check_buyer_address";
const FLAG = "custom_send_as_simplified";

frappe.ui.form.on("Sales Invoice", {
    before_submit(frm) {
        if (!frm.doc.customer || frm.doc.is_return || frm.doc[FLAG]) return;

        return frappe.call({ method: API, args: { customer: frm.doc.customer } }).then((r) => {
            const missing = (r.message && r.message.missing) || [];
            if (!missing.length) return;

            return new Promise((resolve) => {
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
                        d.hide();
                        frm.doc[FLAG] = 1;
                        resolve();
                    },
                    secondary_action_label: __("Cancel"),
                    secondary_action() {
                        d.hide();
                    },
                });
                // Closing the dialog any other way stops the submit too.
                d.onhide = () => {
                    if (!frm.doc[FLAG]) {
                        frappe.validated = false;
                        resolve();
                    }
                };
                d.show();
            });
        });
    },
});

})();
