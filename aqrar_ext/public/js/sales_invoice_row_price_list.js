// aqrar_ext: per-row Price List on selling documents and Purchase Invoice (ported from sf_trading).
//
// Each row can override the document's Price List (custom_price_list). When set
// (or left blank, in which case the document's own Price List applies), the row's
// rate is looked up from that price list — same resolution ERPNext itself uses
// (party pricing, qty breaks, uom fallback, currency conversion).
//
// A row only needs its own lookup when it is priced from a DIFFERENT list than the
// document. When the row's list is the document's list, ERPNext's own rate is
// already right and nothing here runs — that is the usual front-desk case, and it
// used to cost two extra requests and a second rewrite of the same price a second
// after the row appeared.

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

// True when the row is priced from a list other than the document's.
function aqrar_row_overrides_doc_list(frm, row) {
	return !!(row && row.custom_price_list && row.custom_price_list !== aqrar_doc_price_list(frm));
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
			// The user may have changed the item while this was in flight.
			const current = locals[cdt] && locals[cdt][cdn];
			if (!current || current.item_code !== row.item_code) return;
			// Already what the row is priced at: writing it again only redraws the
			// table and re-runs every rate handler for nothing.
			if (flt(current.price_list_rate) === flt(r.message.rate) && flt(current.rate) === flt(r.message.rate)) return;
			frappe.model.set_value(cdt, cdn, "price_list_rate", r.message.rate);
			frappe.model.set_value(cdt, cdn, "rate", r.message.rate);
		},
	});
}

// The document's Price List changed. Rows that were following the old list follow
// the new one; rows with their own list keep it. ERPNext re-rates every row from the
// document's list, so once that has finished the rows with their own list are priced
// again — waiting for the requests to drain, not for a fixed number of milliseconds.
function aqrar_on_doc_price_list_change(frm) {
	const now = aqrar_doc_price_list(frm);
	const prev = frm.__aqrar_prev_price_list;
	frm.__aqrar_prev_price_list = now;

	(frm.doc.items || []).forEach(function (row) {
		if (row.item_code && (!row.custom_price_list || row.custom_price_list === prev)) {
			aqrar_ext.fd.set_quiet(frm, row.doctype, row.name, "custom_price_list", now);
		}
	});

	setTimeout(function () {
		frappe.after_ajax(function () {
			(frm.doc.items || []).forEach(function (row) {
				if (row.item_code && aqrar_row_overrides_doc_list(frm, row)) {
					aqrar_apply_row_price_list(frm, row.doctype, row.name);
				}
			});
		});
	}, 0);
}

Object.keys(AQRAR_ROW_PL_DOCTYPES).forEach(function (parent_dt) {
	frappe.ui.form.on(AQRAR_ROW_PL_DOCTYPES[parent_dt], {
		// The user picked a list for this row on purpose: always price it from that.
		custom_price_list: function (frm, cdt, cdn) { aqrar_apply_row_price_list(frm, cdt, cdn); },
		item_code: function (frm, cdt, cdn) {
			// Our handler runs before ERPNext's own item_code handler, which re-rates
			// the row from the document's list. Only a row with its OWN list needs
			// pricing again, and only after ERPNext has finished.
			const row = locals[cdt][cdn];
			if (!row || !row.item_code || !aqrar_row_overrides_doc_list(frm, row)) return;
			aqrar_ext.fd.when_item_ready(cdt, cdn, row.item_code, function () {
				aqrar_apply_row_price_list(frm, cdt, cdn);
			});
		},
		items_add: function (frm, cdt, cdn) {
			// Show the document's list on the new row. Written quietly: it is the
			// default, not a choice, and must not trigger the lookup above.
			const row = locals[cdt][cdn];
			if (row && !row.custom_price_list && aqrar_doc_price_list(frm)) {
				aqrar_ext.fd.set_quiet(frm, cdt, cdn, "custom_price_list", aqrar_doc_price_list(frm));
			}
		},
	});

	frappe.ui.form.on(parent_dt, {
		// Selling documents offer only selling Price Lists, Purchase Invoice only
		// buying ones (the Selling / Buying checkboxes on the Price List).
		setup: function (frm) {
			const flag = parent_dt === "Purchase Invoice" ? "buying" : "selling";
			// The search lists each Price List with this row's item rate beside it.
			frm.set_query("custom_price_list", "items", function (doc, cdt, cdn) {
				const row = locals[cdt][cdn] || {};
				return {
					query: "aqrar_ext.api.price_list_query.row_price_list_query",
					filters: { item_code: row.item_code || "", buying: flag === "buying" ? 1 : 0 },
				};
			});
		},
		onload: function (frm) {
			frm.__aqrar_prev_price_list = aqrar_doc_price_list(frm);
		},
		selling_price_list: aqrar_on_doc_price_list_change,
		buying_price_list: aqrar_on_doc_price_list_change,
	});
});


// Show each option as one line, "R-Price - 1.80": Frappe puts the description on a
// second line, so put it back inline for this field's dropdown only.
(function () {
	if (!document.getElementById("aqrar-pl-inline-style")) {
		const style = document.createElement("style");
		style.id = "aqrar-pl-inline-style";
		style.textContent =
			".aqrar-pl-inline li br { display: none; }" +
			".aqrar-pl-inline li .small { display: inline; margin-left: 4px; color: var(--text-color); }";
		document.head.appendChild(style);
	}
	$(document).on("awesomplete-open", 'input[data-fieldname="custom_price_list"]', function () {
		$(this).closest(".awesomplete").find("ul").addClass("aqrar-pl-inline");
	});
})();
