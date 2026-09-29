// Mirrors aqrar_ext.overrides.payment_entry.SKIP_TRANSACTION_REFERENCE_MOP:
// reference_no/reference_date carry mandatory_depends_on
// "paid_from_account_type == 'Bank' || paid_to_account_type == 'Bank'"
// (payment_entry.json). paid_from_account_type/paid_to_account_type are
// themselves `fetch_from: paid_from.account_type` / `paid_to.account_type`,
// resolved asynchronously after paid_from/paid_to change — so this can't just
// run on the paid_from/paid_to trigger, it has to run again once that fetch
// lands and core re-evaluates mandatory_depends_on back to reqd.
const SKIP_TRANSACTION_REFERENCE_MOP = ["Bank Transfer"];

function apply_reference_reqd(frm) {
	if (!SKIP_TRANSACTION_REFERENCE_MOP.includes(frm.doc.mode_of_payment)) return;
	frm.toggle_reqd(["reference_no", "reference_date"], 0);
}

frappe.ui.form.on("Payment Entry", {
	refresh: apply_reference_reqd,
	mode_of_payment: apply_reference_reqd,
	paid_from_account_type: apply_reference_reqd,
	paid_to_account_type: apply_reference_reqd,
});
