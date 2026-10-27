// CR-024: customer creation.
//
// Quick Entry ("+ New Customer", also from a Sales Invoice) asks, in this order:
// VAT number, English name, Arabic name, CR number, customer type; one contact
// (name + mobile); the national address (street, building number, district,
// city, postal code, country = Saudi Arabia).
// The address is mandatory once a VAT number is entered: a standard (B2B) tax
// invoice needs the buyer's address for ZATCA, a walk-in customer without VAT
// does not (CR-025). Building number and district are copied onto the primary
// Address by aqrar_ext.overrides.customer.copy_quick_entry_address.
//
// Fields that exist only on some sites (Arabic name, CR number) are offered
// only where the Customer has them. Loaded from app_include_js so it replaces
// ERPNext's CustomerQuickEntryForm before any dialog opens.

(function () {

const NEEDS_ADDRESS = "eval:doc.custom_vat_registration_number";

function customer_has(fieldname) {
    return !!frappe.meta.get_docfield("Customer", fieldname);
}

class AqrarCustomerQuickEntryForm extends frappe.ui.form.ContactAddressQuickEntryForm {
    render_dialog() {
        // ContactAddressQuickEntryForm appends get_variant_fields() to the meta's
        // mandatory fields; we lay the whole dialog out ourselves instead.
        const by_name = {};
        this.mandatory.forEach((df) => (by_name[df.fieldname] = df));
        const pick = (fieldname, extra) => {
            const df = by_name[fieldname] || frappe.meta.get_docfield("Customer", fieldname);
            return df ? Object.assign({}, df, extra || {}) : null;
        };

        const top = [
            customer_has("custom_vat_registration_number") &&
                pick("custom_vat_registration_number", { label: __("VAT Number"), description: "" }),
            pick("customer_name", { label: __("Customer Name (English)") }),
            customer_has("custom_customer_arabic_name") &&
                pick("custom_customer_arabic_name", { label: __("Customer Name (Arabic)") }),
            customer_has("custom_cr_number") && pick("custom_cr_number"),
            pick("customer_type"),
        ].filter(Boolean);

        const taken = new Set(top.map((df) => df.fieldname));
        // keep any other field the site made mandatory, so the insert can't fail on it
        const rest = this.mandatory.filter((df) => df.reqd && !taken.has(df.fieldname));

        this.mandatory = top.concat(rest, this.get_variant_fields());
        frappe.ui.form.QuickEntryForm.prototype.render_dialog.call(this);
        if (!this.dialog.get_value("country")) this.dialog.set_value("country", "Saudi Arabia");
    }

    get_variant_fields() {
        return [
            { fieldtype: "Section Break", label: __("Contact"), collapsible: 0 },
            { label: __("Contact Name"), fieldname: "map_to_first_name", fieldtype: "Data" },
            { fieldtype: "Column Break" },
            { label: __("Mobile Number"), fieldname: "mobile_number", fieldtype: "Data" },
            {
                fieldtype: "Section Break",
                label: __("National Address"),
                description: __("Required when a VAT number is entered."),
                collapsible: 0,
            },
            { label: __("Street Name"), fieldname: "address_line1", fieldtype: "Data", mandatory_depends_on: NEEDS_ADDRESS },
            { label: __("Building Number"), fieldname: "custom_building_number", fieldtype: "Data", mandatory_depends_on: NEEDS_ADDRESS },
            { label: __("District"), fieldname: "custom_area", fieldtype: "Data", mandatory_depends_on: NEEDS_ADDRESS },
            { fieldtype: "Column Break" },
            { label: __("City"), fieldname: "city", fieldtype: "Data", mandatory_depends_on: NEEDS_ADDRESS },
            { label: __("Postal Code"), fieldname: "pincode", fieldtype: "Data", mandatory_depends_on: NEEDS_ADDRESS },
            { label: __("Country"), fieldname: "country", fieldtype: "Link", options: "Country", mandatory_depends_on: NEEDS_ADDRESS },
        ];
    }

    insert() {
        // A street alone makes ERPNext create the Address; only then is the rest needed.
        const doc = this.dialog.doc;
        if (!doc.address_line1) {
            ["custom_building_number", "custom_area", "city", "pincode"].forEach((f) => delete doc[f]);
        }
        return super.insert();
    }
}

frappe.ui.form.CustomerQuickEntryForm = AqrarCustomerQuickEntryForm;

// Full Customer form: VAT, names and CR are moved up by
// setup_data.ensure_customer_form_order; here the fields the client does not
// use are hidden for everyone but System Managers.
const HIDDEN_FOR_STAFF = [
    "salutation", "gender", "lead_name", "opportunity_name", "prospect_name",
    "account_manager", "customer_group", "default_currency", "default_price_list",
];

frappe.ui.form.on("Customer", {
    refresh(frm) {
        if (frappe.user.has_role("System Manager")) return;
        HIDDEN_FOR_STAFF.forEach((f) => {
            const field = frm.get_field(f);
            // never hide a mandatory field that is still empty, or the save would fail unseen
            if (field && !(field.df.reqd && !frm.doc[f])) frm.toggle_display(f, false);
        });
    },
});

})();
