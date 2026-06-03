frappe.ui.form.on("Sales Invoice", {
    onload(frm) {
        handle_return_invoice(frm);
    },
    refresh(frm) {
        handle_return_invoice(frm);
    },
    validate(frm) {
        if (!frm.doc.is_return) return;
        (frm.doc.items || []).forEach(row => {
            if (row.qty > 0) {
                row.qty = -Math.abs(row.qty);
            }
        });
    }
});


function handle_return_invoice(frm) {
    if (!frm.doc.is_return) return;
    let changed = false;
    (frm.doc.items || []).forEach(row => {
        if (row.qty < 0) {

            row.qty = Math.abs(row.qty);
            changed = true;
        }
    });
    if (changed) {
        frm.refresh_field("items");
    }
}