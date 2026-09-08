// Default `custom_sales_person` from the user's own User Permissions.
//
// Frappe already does this for a Link field — but only when the field's
// `ignore_user_permissions` is 0. Both branches of create_new.js
// get_default_value are gated on that flag, and we need it set to 1: without it,
// a User Permission on Sales Person would filter the whole Sales Invoice / Sales
// Order list down to that person's documents the moment the link field exists.
//
// So the flag stays on and the default is done here instead, using Frappe's own
// helper so the semantics match core exactly: prefer the permission flagged
// Is Default, otherwise a single permission.
//
// utils/sales_team.py repeats this server-side, so an invoice created by import
// or API gets the same salesman a person would have got.

(function () {

const SALES_PERSON_DOCTYPES = ["Sales Invoice", "Sales Order"];

function permitted_sales_person(doctype) {
    const all = frappe.defaults.get_user_permissions();
    if (!all || !all["Sales Person"]) return null;

    const { allowed_records, default_doc } = frappe.perm.filter_allowed_docs_for_doctype(
        all["Sales Person"],
        doctype
    );

    if (default_doc) return default_doc;
    // Core only falls back to a lone permission, not to the first of several:
    // picking one of many would be a guess at who made the sale.
    return allowed_records && allowed_records.length === 1 ? allowed_records[0] : null;
}

// Keep the Sales Team row in step with the field as it is edited. The server does
// this too and is the authority — this exists so the grid does not sit showing
// the previous salesman until the next save.
//
// `mirrored` tracks which person our row currently names, so a row somebody
// typed themselves is never touched. It mirrors the server's rule: on a saved
// document the header and our row agree, so the loaded value identifies our row.
function sync_sales_team(frm) {
    const person = frm.doc.custom_sales_person || null;
    const rows = frm.doc.sales_team || [];
    const previous = frm.__mirrored_sales_person || null;
    const ours = rows.length === 1 && previous && rows[0].sales_person === previous;

    if (ours) {
        if (!person) {
            frm.clear_table("sales_team");
        } else if (rows[0].sales_person !== person) {
            rows[0].sales_person = person;
            rows[0].allocated_percentage = 100;
        }
    } else if (!rows.length && person) {
        frm.add_child("sales_team", { sales_person: person, allocated_percentage: 100 });
    } else {
        // somebody else's rows — leave them, and stop claiming ownership
        frm.__mirrored_sales_person = null;
        return;
    }

    frm.__mirrored_sales_person = person;
    frm.refresh_field("sales_team");
}

for (const doctype of SALES_PERSON_DOCTYPES) {
    frappe.ui.form.on(doctype, {
        onload(frm) {
            // On a saved document our row already agrees with the header, so the
            // loaded value is what identifies the row as ours.
            frm.__mirrored_sales_person = frm.doc.custom_sales_person || null;

            if (!frm.is_new() || frm.doc.custom_sales_person) return;

            const person = permitted_sales_person(frm.doctype);
            if (person) frm.set_value("custom_sales_person", person);
        },

        custom_sales_person(frm) {
            sync_sales_team(frm);
        }
    });
}

})();
