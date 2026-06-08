frappe.ui.form.on('Payment Entry', {
    refresh: function(frm) {
        set_reference_mandatory(frm);
    },
    mode_of_payment: function(frm) {
        set_reference_mandatory(frm);
    }
});

function set_reference_mandatory(frm) {
    const bank_modes = ['Bank Transfer', 'Cheque'];
    const is_bank = bank_modes.includes(frm.doc.mode_of_payment);
    frm.toggle_reqd('reference_no', is_bank);
}