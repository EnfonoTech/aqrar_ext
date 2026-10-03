// aqrar_ext: per-row Price List on selling documents and Purchase Invoice (ported from sf_trading).
//
// Each row can override the document's Price List (custom_price_list). When set
// (or left blank, in which case the document's own Price List applies), the row's
// rate is looked up from that price list — same resolution ERPNext itself uses
// (party pricing, qty breaks, uom fallback, currency conversion).

var AQRAR_ROW_PL_DOCTYPES = {
	"Sales Invoice": "Sales Invoice Item",
	"Quotation": "Quotation Item",
	"Sales Order": "Sales Order Item",
	"Delivery Note": "Delivery Note Item",
	"Purchase Invoice": "Purchase Invoice Item",
};

// Purchase documents carry a buying price list instead of a selling one.
function aqrar_doc_price_list(frm) {
	return frm.doc.selling_price_list || frm.doc.buying_price_list;
}

function aqrar_row_pl_customer(frm) {
	if (frm.doc.customer) return frm.doc.customer;
	// Quotation can be addressed to a Lead / Prospect as well
	return frm.doc.quotation_to === "Customer" ? frm.doc.party_name : null;
}

function aqrar_apply_row_price_list(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.item_code) return;
	const price_list = row.custom_price_list || aqrar_doc_price_list(frm);
	if (!price_list) return;

	frappe.call({
		method: "aqrar_ext.api.item_row_price_list.get_row_price_list_rate",
		args: {
			item_code: row.item_code,
			price_list: price_list,
			doctype: frm.doc.doctype,
			uom: row.uom,
			stock_uom: row.stock_uom,
			qty: row.qty || 1,
			transaction_date: frm.doc.posting_date || frm.doc.transaction_date || frappe.datetime.get_today(),
			customer: aqrar_row_pl_customer(frm),
			supplier: frm.doc.supplier,
			company: frm.doc.company,
			conversion_rate: frm.doc.conversion_rate || 1,
		},
		callback: function (r) {
			if (!r.message || !flt(r.message.rate)) return;
			frappe.model.set_value(cdt, cdn, "price_list_rate", r.message.rate);
			frappe.model.set_value(cdt, cdn, "rate", r.message.rate);
		},
	});
}

// ERPNext's own price-list-change handler re-rates every row against the
// document's price list a moment later — reapply row-level overrides afterwards
// so they aren't clobbered by that.
function aqrar_reapply_row_price_lists(frm) {
	setTimeout(function () {
		(frm.doc.items || []).forEach(function (row) {
			if (row.item_code && row.custom_price_list) {
				aqrar_apply_row_price_list(frm, row.doctype, row.name);
			}
		});
	}, 700);
}

Object.keys(AQRAR_ROW_PL_DOCTYPES).forEach(function (parent_dt) {
	frappe.ui.form.on(AQRAR_ROW_PL_DOCTYPES[parent_dt], {
		custom_price_list: function (frm, cdt, cdn) { aqrar_apply_row_price_list(frm, cdt, cdn); },
		item_code: function (frm, cdt, cdn) {
			// ERPNext's own item_code handler re-rates the row from the document's
			// price list a moment later — reapply the row's own price list (if any)
			// afterwards so it isn't clobbered by that.
			const row = locals[cdt][cdn];
			if (row && row.custom_price_list) {
				setTimeout(function () { aqrar_apply_row_price_list(frm, cdt, cdn); }, 800);
			}
		},
		items_add: function (frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (row && !row.custom_price_list && aqrar_doc_price_list(frm)) {
				frappe.model.set_value(cdt, cdn, "custom_price_list", aqrar_doc_price_list(frm));
			}
		},
	});

	frappe.ui.form.on(parent_dt, {
		selling_price_list: aqrar_reapply_row_price_lists,
		buying_price_list: aqrar_reapply_row_price_lists,
	});
});
