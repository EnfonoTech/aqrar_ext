// Party balance on the header of Sales and Purchase documents, shown when the party
// is selected (like "Party Balance" on Payment Entry): the customer's / supplier's
// ledger balance as of the document date. Display only, written straight onto the
// document so looking at it never marks the form as changed.

(function () {
    const FIELD = "custom_party_balance";

    const DOCS = {
        "Sales Invoice": { party_type: "Customer", party: "customer", date: "posting_date" },
        "Delivery Note": { party_type: "Customer", party: "customer", date: "posting_date" },
        "Sales Order": { party_type: "Customer", party: "customer", date: "transaction_date" },
        "Quotation": { party_type: "Customer", party: "party_name", date: "transaction_date" },
        "Purchase Invoice": { party_type: "Supplier", party: "supplier", date: "posting_date" },
        "Purchase Order": { party_type: "Supplier", party: "supplier", date: "transaction_date" },
        "Purchase Receipt": { party_type: "Supplier", party: "supplier", date: "posting_date" },
    };

    function show(frm, value) {
        frm.doc[FIELD] = value;
        frm.refresh_field(FIELD);
    }

    function update(frm) {
        const cfg = DOCS[frm.doctype];
        const party = frm.doc[cfg.party];
        // A Quotation can be addressed to a Lead / Prospect, which has no ledger.
        const applies = party && (frm.doctype !== "Quotation" || frm.doc.quotation_to === "Customer");
        if (!applies) return show(frm, null);

        // refresh fires on every save / reload; only ask again when what the balance
        // depends on (or the document's state) has changed.
        const key = [party, frm.doc.company, frm.doc[cfg.date], frm.doc.docstatus].join("|");
        if (frm.__party_balance_key === key) return;
        frm.__party_balance_key = key;

        frappe.call({
            method: "aqrar_ext.api.party_balance.get_party_balance",
            args: {
                party_type: cfg.party_type,
                party: party,
                company: frm.doc.company,
                date: frm.doc[cfg.date],
            },
            callback(r) {
                // the party may have changed while the call was out
                if (frm.doc[cfg.party] !== party) {
                    frm.__party_balance_key = null;
                    return;
                }
                show(frm, r.message === undefined ? null : r.message);
            },
        });
    }

    Object.entries(DOCS).forEach(([doctype, cfg]) => {
        const handlers = { refresh: update, company: update };
        handlers[cfg.party] = update;
        handlers[cfg.date] = update;
        if (doctype === "Quotation") handlers.quotation_to = update;
        frappe.ui.form.on(doctype, handlers);
    });
})();
