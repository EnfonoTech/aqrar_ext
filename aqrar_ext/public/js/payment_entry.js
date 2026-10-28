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

// CR-030 (ticket #5): tick-to-allocate.
// Selecting a customer (Receive) or supplier (Pay) on a new entry lists every
// outstanding invoice / JV with the allocated amount left blank. Ticking a row
// fills it; while no paid amount has been typed, the paid amount follows the
// ticked total. ERPNext's own oldest-first spreading of the paid amount
// (allocate_party_amount_against_ref_docs -> allocate_amount_to_references) is
// switched off for these entries, because backdated payments landed on the
// wrong invoices. The "Get Outstanding Invoices" button keeps core behaviour.
const TICK_PARTY_TYPE = { Receive: "Customer", Pay: "Supplier" };

function tick_mode(frm) {
	if (frm.doc.docstatus !== 0) return false;
	if (frm._aqrar_tick) return true;
	return (frm.doc.references || []).some((row) => row.custom_allocate);
}

// core's `party` handler fills the party account and then clears references
// in a frappe.run_serially chain it does not return; its last step resets
// set_party_account_based_on_party. Wait for that before adding rows.
async function wait_for_party_details(frm) {
	for (let i = 0; i < 100 && frm.set_party_account_based_on_party; i++) {
		await new Promise((resolve) => setTimeout(resolve, 100));
	}
}

async function load_outstanding_for_tick(frm) {
	const party = frm.doc.party;
	if (!frm.is_new() || !party || TICK_PARTY_TYPE[frm.doc.payment_type] !== frm.doc.party_type) return;

	await wait_for_party_details(frm);
	const party_account = frm.doc.payment_type == "Receive" ? frm.doc.paid_from : frm.doc.paid_to;
	if (frm.doc.party !== party || !party_account) return;

	const r = await frappe.call({
		method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_outstanding_reference_documents",
		args: {
			args: {
				posting_date: frm.doc.posting_date,
				company: frm.doc.company,
				party_type: frm.doc.party_type,
				payment_type: frm.doc.payment_type,
				party: party,
				party_account: party_account,
				cost_center: frm.doc.cost_center,
				get_outstanding_invoices: true,
				book_advance_payments_in_separate_party_account:
					frm.doc.book_advance_payments_in_separate_party_account,
			},
		},
	});
	if (frm.doc.party !== party) return; // party changed while loading

	const company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
	const party_account_currency =
		frm.doc.payment_type == "Receive" ? frm.doc.paid_from_account_currency : frm.doc.paid_to_account_currency;

	frm._aqrar_tick = true;
	frm._aqrar_auto_paid = null;
	frm.clear_table("references");
	// Oldest first, opening-balance JVs included (core lists JVs after invoices).
	const docs = (r.message || []).slice().sort((a, b) => (a.posting_date || "").localeCompare(b.posting_date || ""));
	docs.forEach((d) => {
		const row = frm.add_child("references");
		row.reference_doctype = d.voucher_type;
		row.reference_name = d.voucher_no;
		row.due_date = d.due_date;
		row.total_amount = d.invoice_amount;
		row.outstanding_amount = d.outstanding_amount;
		row.bill_no = d.bill_no;
		row.payment_term = d.payment_term;
		row.payment_term_outstanding = d.payment_term_outstanding;
		row.account = d.account;
		row.exchange_rate = party_account_currency != company_currency ? d.exchange_rate : 1;
		row.allocated_amount = 0;
		row.custom_allocate = 0;
	});
	frm.refresh_field("references");
	frm.events.set_total_allocated_amount(frm);
}

// Amount a ticked row receives: its full outstanding while the paid amount
// follows the ticks; otherwise what is left of the typed paid amount (a credit
// note / negative row frees money, so it always takes its full amount).
function tick_amount(frm, row) {
	const outstanding = flt(row.outstanding_amount);
	if (outstanding < 0 || frm._aqrar_auto_paid != null) return outstanding;
	const left = flt(frm.doc.paid_amount) - (allocated_total(frm) - flt(row.allocated_amount));
	return flt(Math.max(0, Math.min(outstanding, left)), precision("allocated_amount", row));
}

function allocated_total(frm) {
	return (frm.doc.references || []).reduce((sum, row) => sum + flt(row.allocated_amount), 0);
}

// While the paid amount is "ours" (blank when the first row was ticked, or
// still the total we last wrote), keep it equal to the ticked total.
function sync_paid_amount(frm) {
	if (frm._aqrar_auto_paid === null || frm._aqrar_auto_paid === undefined) return;
	const total = flt(Math.abs(allocated_total(frm)), precision("paid_amount"));
	frm._aqrar_auto_paid = total;
	frm.set_value("paid_amount", total);
}

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		const core_allocate = frm.events.allocate_party_amount_against_ref_docs;
		if (!core_allocate || core_allocate._aqrar) return;
		const allocate = function (frm, paid_amount, paid_amount_change) {
			// paid_amount_change false = core "Get Outstanding Invoices" dialog,
			// which asks for its own allocation: hand back to core.
			if (paid_amount_change && tick_mode(frm)) {
				frm.events.set_total_allocated_amount(frm);
				return Promise.resolve();
			}
			if (!paid_amount_change) frm._aqrar_tick = false;
			return core_allocate(frm, paid_amount, paid_amount_change);
		};
		allocate._aqrar = true;
		frm.events.allocate_party_amount_against_ref_docs = allocate;
	},
	party(frm) {
		frm._aqrar_tick = false;
		return load_outstanding_for_tick(frm);
	},
	paid_amount(frm) {
		// Typed by the user: stop following the ticked total.
		if (flt(frm.doc.paid_amount) === frm._aqrar_auto_paid) return;
		frm._aqrar_auto_paid = null;
		if (tick_mode(frm)) return trim_to_paid_amount(frm);
	},
});

frappe.ui.form.on("Payment Entry Reference", {
	custom_allocate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row._aqrar_setting) return;
		if (row.custom_allocate && !flt(frm.doc.paid_amount) && frm._aqrar_auto_paid == null) {
			frm._aqrar_auto_paid = 0; // paid amount is blank: it follows the ticks from now on
		}
		const amount = row.custom_allocate ? flt(tick_amount(frm, row)) : 0;
		if (row.custom_allocate && !amount) {
			frappe.show_alert({ message: __("Nothing left of the paid amount to allocate"), indicator: "orange" });
			set_row(frm, row, { custom_allocate: 0 });
			return;
		}
		set_row(frm, row, { allocated_amount: amount });
	},
	allocated_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row._aqrar_setting && tick_mode(frm) && !!flt(row.allocated_amount) !== !!row.custom_allocate) {
			// typed by hand: keep the tick in step without re-filling the amount
			set_row(frm, row, { custom_allocate: flt(row.allocated_amount) ? 1 : 0 });
		}
		if (tick_mode(frm)) sync_paid_amount(frm);
	},
});

// A typed paid amount below the ticked total: take the excess back from the
// last ticked rows (bottom of the table first), unticking rows left at 0.
async function trim_to_paid_amount(frm) {
	let excess = flt(allocated_total(frm) - flt(frm.doc.paid_amount), precision("paid_amount"));
	if (excess <= 0) return;
	const rows = (frm.doc.references || []).filter((r) => flt(r.allocated_amount) > 0).reverse();
	for (const row of rows) {
		if (excess <= 0) break;
		const cut = Math.min(excess, flt(row.allocated_amount));
		const left = flt(flt(row.allocated_amount) - cut, precision("allocated_amount", row));
		excess = flt(excess - cut, precision("paid_amount"));
		await set_row(frm, row, { allocated_amount: left, custom_allocate: left ? 1 : 0 });
	}
	frappe.show_alert({ message: __("Allocation reduced to the paid amount"), indicator: "orange" });
}

function set_row(frm, row, values) {
	row._aqrar_setting = true;
	return frappe.model
		.set_value(row.doctype, row.name, values)
		.then(() => {
			row._aqrar_setting = false;
			frm.events.set_total_allocated_amount(frm);
			sync_paid_amount(frm);
		});
}

// CR-028 (ticket #3): compact form. Display-only, so it sits on top of the
// field order set on site (Property Setter) instead of rewriting it.
// The Accounts section keeps only the company side (bank/cash) and its balance;
// the party side is filled from the party and its balance shows as Party Balance.
function compact_layout(frm) {
	const is_party_payment = ["Receive", "Pay"].includes(frm.doc.payment_type) && frm.doc.party_type;
	const party_side = frm.doc.payment_type == "Receive" ? "paid_from" : "paid_to";
	const company_side = party_side == "paid_from" ? "paid_to" : "paid_from";
	const company_currency = frm.doc.company && frappe.get_doc(":Company", frm.doc.company)?.default_currency;

	const hide_party_side = !!(is_party_payment && frm.doc[party_side]);
	["paid_from", "paid_from_account_currency", "paid_from_account_balance",
		"paid_to", "paid_to_account_currency", "paid_to_account_balance"].forEach((f) => {
		const side = f.startsWith("paid_from") ? "paid_from" : "paid_to";
		let show = !(hide_party_side && side == party_side);
		if (show && f.endsWith("_currency")) {
			// same-currency entries need no currency field (always SAR here)
			show = !company_currency || frm.doc[f] != company_currency || !frm.doc[side];
		}
		frm.toggle_display(f, show);
	});
	frm.toggle_display(company_side, true);

	frm.toggle_display("get_outstanding_orders", false);
	// Advance taxes only matter on a prepayment invoice; their table sits
	// outside the collapsed Taxes section, so hide it while it is unused.
	const uses_taxes = (frm.doc.taxes || []).length || frm.doc.custom_prepayment_invoice;
	// (hiding the section hides its fields; core toggles base_* itself)
	["section_break_56", "section_break_60"].forEach((f) => frm.toggle_display(f, !!uses_taxes));
}

frappe.ui.form.on("Payment Entry", {
	refresh: compact_layout,
	payment_type: compact_layout,
	party_type: compact_layout,
	paid_from: compact_layout,
	paid_to: compact_layout,
	custom_prepayment_invoice: compact_layout,
	paid_from_account_currency: compact_layout,
	paid_to_account_currency: compact_layout,
});
