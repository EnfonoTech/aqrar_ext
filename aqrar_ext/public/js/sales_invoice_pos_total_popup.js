// aqrar_ext: Sales Invoice payment popup (CR-007)
//
// Ported from the Steel Force (sf_trading) production implementation so the two
// behave the same way. Deviations are marked ADAPTED and exist only because this
// site does not carry the fields Steel Force does.
//
// The flow is driven by `custom_payment_mode` on the invoice:
//   Credit  -> confirm, then submit; no Payment Entry
//   Cheque  -> post-dated cheque popup (dormant until "Cheque" is an option)
//   other   -> payment popup, one row per allowed Mode of Payment
//
// Payment modes come from the branch allowlist (Branch Configuration Mode of
// Payment). POS Profile is never consulted.

function aqrar_open_invoice_print(frm) {
	if (!frm || !frm.doc || !frm.doc.name) return;
	// ADAPTED: Steel Force reads a per-company print format; this site has no
	// such field, so the doctype default is used.
	const format = encodeURIComponent(frm.meta.default_print_format || "");
	const url =
		`${window.location.origin}/printview?doctype=Sales%20Invoice` +
		`&name=${encodeURIComponent(frm.doc.name)}` +
		`&trigger_print=1&format=${format}&no_letterhead=0&settings=%7B%7D` +
		`&_lang=${frappe.boot.lang}`;
	const a = document.createElement("a");
	a.href = url;
	a.target = "_blank";
	a.rel = "noopener noreferrer";
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
}

function aqrar_currency_precision(currency_code) {
	const currency_doc = frappe.model.get_doc(":Currency", currency_code);
	if (currency_doc && currency_doc.number_format) {
		return get_number_format_info(currency_doc.number_format).precision;
	}
	return cint(frappe.boot.sysdefaults.currency_precision) || 2;
}

function aqrar_amount_to_pay(frm, precision) {
	return flt(
		Math.abs(
			flt(
				(frm.doc.outstanding_amount > 0 ? frm.doc.outstanding_amount : null) ||
					frm.doc.rounded_total ||
					frm.doc.grand_total ||
					0
			)
		),
		precision
	);
}

function aqrar_is_credit(frm) {
	return frm.doc.custom_payment_mode === "Credit";
}

function aqrar_is_cheque(frm) {
	return frm.doc.custom_payment_mode === "Cheque";
}

function aqrar_submit_and_print(frm) {
	return frm.save("Submit").then(function () {
		if (frm.doc.docstatus === 1) {
			aqrar_open_invoice_print(frm);
			frm.reload_doc();
		}
	});
}

frappe.ui.form.on("Sales Invoice", {
	before_submit: function (frm) {
		// Cheque -> post-dated cheque popup
		if (aqrar_is_cheque(frm)) {
			frappe.validated = false;
			if (Math.abs(flt(frm.doc.grand_total)) > 0 && Math.abs(flt(frm.doc.outstanding_amount)) > 0) {
				aqrar_show_pdc_popup(frm);
			} else {
				aqrar_submit_and_print(frm);
			}
			return;
		}

		// Cash / Card -> payment popup
		if (!aqrar_is_credit(frm)) {
			frappe.validated = false;
			if (Math.abs(flt(frm.doc.grand_total)) > 0 && Math.abs(flt(frm.doc.outstanding_amount)) > 0) {
				aqrar_show_payment_popup(frm);
			} else {
				aqrar_submit_and_print(frm);
			}
			return;
		}

		// Credit -> confirm, then submit without collecting
		frappe.validated = false;
		frappe.confirm(__("Do you want to Submit this Sales Invoice?"), function () {
			aqrar_submit_and_print(frm);
		});
	},

	after_save: function (frm) {
		if (frappe.flags.aqrar_skip_payment_popup) return;
		if (frappe.flags.aqrar_popup_showing) return;
		if (frm.doc.docstatus !== 0) return;
		if (!frm.doc.name || String(frm.doc.name).startsWith("new-")) return;

		if (aqrar_is_credit(frm)) {
			if (frappe.flags.aqrar_credit_confirm_open) return;
			frappe.flags.aqrar_credit_confirm_open = true;
			const d = frappe.confirm(
				__("Do you want to Submit this Sales Invoice now?"),
				function () {
					frappe.flags.aqrar_skip_payment_popup = true;
					aqrar_submit_and_print(frm).finally(function () {
						setTimeout(function () {
							delete frappe.flags.aqrar_skip_payment_popup;
						}, 500);
					});
				},
				function () {
					/* No: the invoice is saved, nothing more to do */
				}
			);
			if (d) {
				d.onhide = function () {
					delete frappe.flags.aqrar_credit_confirm_open;
				};
			}
			return;
		}

		if (!frm.doc.grand_total || Math.abs(flt(frm.doc.grand_total)) <= 0) return;
		if (Math.abs(flt(frm.doc.outstanding_amount)) <= 0) return;

		if (aqrar_is_cheque(frm)) {
			aqrar_show_pdc_popup(frm);
			return;
		}
		aqrar_show_payment_popup(frm);
	},
});

// ── Cash / Card payment popup ────────────────────────────────────────────────

function aqrar_show_payment_popup(frm) {
	if (frappe.flags.aqrar_popup_showing) return;
	if (!frm || !frm.doc) return;
	frappe.flags.aqrar_popup_showing = true;

	frappe.call({
		method: "aqrar_ext.api.sales_invoice.get_payment_modes_with_account",
		args: {
			company: frm.doc.company,
			is_return: frm.doc.is_return ? 1 : 0,
			is_pdc: 0,
		},
		callback: function (r) {
			const modes = r.message || [];
			if (!modes.length) {
				frappe.flags.aqrar_popup_showing = false;
				frappe.msgprint(
					__(
						"No Mode of Payment is available. Set a default Cash or Bank account on the Mode of Payment, and add it to this branch's Branch Configuration."
					)
				);
				return;
			}
			aqrar_render_payment_dialog(frm, modes);
		},
		error: function () {
			frappe.flags.aqrar_popup_showing = false;
			frappe.msgprint(__("Error loading payment modes. Please try again."));
		},
	});
}

function aqrar_render_payment_dialog(frm, modes) {
	const currency = frm.doc.currency || "";
	const precision = aqrar_currency_precision(currency);
	const invoice_total = aqrar_amount_to_pay(frm, precision);

	if (invoice_total <= 0) {
		frappe.flags.aqrar_popup_showing = false;
		frappe.msgprint(__("Invoice total must be greater than zero."));
		return;
	}

	const fields = [
		{
			fieldname: "invoice_total",
			fieldtype: "Currency",
			label: __("Amount to Pay"),
			default: invoice_total,
			read_only: 1,
			options: "currency",
			precision: precision,
		},
		{ fieldtype: "Section Break", label: __("Enter Payment Amounts") },
	];

	modes.forEach(function (mode, idx) {
		fields.push(
			{ fieldtype: "Section Break", fieldname: "row_" + idx, label: "", hide_border: 1, collapsible: 0 },
			{
				fieldname: "pay_" + idx,
				fieldtype: "Currency",
				label: mode,
				default: idx === 0 && modes.length === 1 ? invoice_total : 0,
				options: "currency",
				precision: precision,
			},
			{ fieldtype: "Column Break", fieldname: "cb_" + idx },
			{
				fieldtype: "Button",
				fieldname: "fill_" + idx,
				label: mode,
				click: function () {
					modes.forEach(function (_, i) {
						d.set_value("pay_" + i, i === idx ? invoice_total : 0);
					});
				},
			}
		);
	});

	function apply_payments_and_close(vals, submit) {
		if (!vals) {
			frappe.msgprint({ title: __("Error"), message: __("Please enter payment amounts."), indicator: "red" });
			return;
		}

		let total = 0;
		const payload = [];
		modes.forEach(function (mode, i) {
			const amt = flt(vals["pay_" + i]) || 0;
			if (amt > 0) {
				payload.push({ mode_of_payment: mode, amount: amt });
				total += amt;
			}
		});

		if (!payload.length) {
			frappe.msgprint({
				title: __("Error"),
				message: __("Please enter at least one payment amount."),
				indicator: "red",
			});
			return;
		}

		const total_rounded = flt(total, precision);

		if (total_rounded - invoice_total > 0.0001) {
			frappe.msgprint({
				title: __("Error"),
				message: __("Total payment amount {0} cannot be greater than amount to pay {1}.", [
					format_currency(total_rounded, currency),
					format_currency(invoice_total, currency),
				]),
				indicator: "red",
			});
			return;
		}

		if (invoice_total - total_rounded > 0.0001) {
			frappe.msgprint({
				title: __("Incomplete"),
				message: __("{0} still to be allocated", [
					format_currency(invoice_total - total_rounded, currency),
				]),
				indicator: "red",
			});
			return;
		}

		const finalize_payments = function () {
			const actual_os = flt(Math.abs(flt(frm.doc.outstanding_amount || 0)), precision);
			if (actual_os > 0 && flt(total_rounded - actual_os) > 0.0001) {
				frappe.msgprint({
					title: __("Payment Error"),
					message: __(
						"Payment total ({0}) exceeds outstanding amount ({1}). The invoice may have advance payments already applied. Please create the payment manually for the correct outstanding amount.",
						[format_currency(total_rounded, currency), format_currency(actual_os, currency)]
					),
					indicator: "red",
				});
				return;
			}
			d.hide();
			frappe.flags.aqrar_popup_showing = false;
			frappe.call({
				method: "aqrar_ext.api.sales_invoice.create_pos_payments_for_invoice",
				args: { sales_invoice: frm.doc.name, payments: JSON.stringify(payload) },
				freeze: true,
				freeze_message: __("Creating payments..."),
				callback: function (r) {
					if (r && r.message && r.message.length) {
						frappe.show_alert(
							{
								message: __("Created {0} Payment Entries for this invoice", [r.message.length]),
								indicator: "green",
							},
							5
						);
					}
					frm.reload_doc();
				},
			});
		};

		if (submit && frm.doc.docstatus === 0) {
			frappe.flags.aqrar_skip_payment_popup = true;
			frm
				.save("Submit")
				.then(function () {
					if (frm.doc.docstatus !== 1) return;
					aqrar_open_invoice_print(frm);
					finalize_payments();
				})
				.finally(function () {
					setTimeout(function () {
						delete frappe.flags.aqrar_skip_payment_popup;
					}, 500);
				});
		} else if (frm.doc.docstatus === 1) {
			finalize_payments();
		} else {
			d.hide();
			frappe.flags.aqrar_popup_showing = false;
			frappe.show_alert(
				{ message: __("Invoice saved. Submit the invoice when ready to add payments."), indicator: "blue" },
				4
			);
		}
	}

	const d = new frappe.ui.Dialog({
		title: __("Enter Payment Amounts"),
		fields: fields,
		primary_action_label: __("Save & Submit"),
		primary_action: function (vals) {
			if (vals) apply_payments_and_close(vals, true);
		},
		secondary_action_label: __("Save"),
		secondary_action: function () {
			if (frm.doc.docstatus === 0) {
				d.hide();
				frappe.flags.aqrar_popup_showing = false;
				frappe.show_alert(
					{ message: __("Invoice saved. Submit the invoice when ready to add payments."), indicator: "blue" },
					4
				);
				frm.reload_doc();
				return;
			}
			const vals = d.get_values();
			if (vals) apply_payments_and_close(vals, false);
		},
		onhide: function () {
			frappe.flags.aqrar_popup_showing = false;
		},
	});

	d.show();

	frappe.utils.sleep(100).then(function () {
		d.$wrapper.find(".section-body").css({ display: "flex", alignItems: "flex-end" });
		// clicking a field fills it with whatever is still unallocated
		modes.forEach(function (_, idx) {
			const field = d.fields_dict["pay_" + idx];
			if (!field || !field.$wrapper) return;
			field.$wrapper
				.find("input")
				.off("click.aqrar_fill")
				.on("click.aqrar_fill", function () {
					let other = 0;
					modes.forEach(function (__, i) {
						if (i !== idx) other += flt(d.get_value("pay_" + i)) || 0;
					});
					d.set_value("pay_" + idx, Math.max(0, flt(invoice_total - other)));
				});
		});
	});
}

// ── Post-dated cheque popup ──────────────────────────────────────────────────
// Loads the for_pdc modes and the ordinary modes so a payment can be split
// between a cheque and cash. Cheque Date / Cheque No apply only to the cheque
// rows. Dormant until "Cheque" is added to custom_payment_mode.

function aqrar_show_pdc_popup(frm) {
	if (frappe.flags.aqrar_popup_showing) return;
	if (!frm || !frm.doc) return;
	frappe.flags.aqrar_popup_showing = true;

	const currency = frm.doc.currency || "";
	const precision = aqrar_currency_precision(currency);
	const invoice_total = aqrar_amount_to_pay(frm, precision);
	const base_args = { company: frm.doc.company, is_return: frm.doc.is_return ? 1 : 0 };

	frappe.call({
		method: "aqrar_ext.api.sales_invoice.get_payment_modes_with_account",
		args: Object.assign({}, base_args, { is_pdc: 1 }),
		callback: function (r1) {
			const cheque_modes = r1.message || [];
			frappe.call({
				method: "aqrar_ext.api.sales_invoice.get_payment_modes_with_account",
				args: Object.assign({}, base_args, { is_pdc: 0 }),
				callback: function (r2) {
					const cash_modes = r2.message || [];
					if (!cheque_modes.length && !cash_modes.length) {
						frappe.flags.aqrar_popup_showing = false;
						frappe.msgprint(__("No payment modes configured for this branch."));
						return;
					}
					show_cheque_dialog(cheque_modes, cash_modes);
				},
				error: function () {
					frappe.flags.aqrar_popup_showing = false;
					frappe.msgprint(__("Error loading payment modes. Please try again."));
				},
			});
		},
		error: function () {
			frappe.flags.aqrar_popup_showing = false;
			frappe.msgprint(__("Error loading cheque payment modes. Please try again."));
		},
	});

	function show_cheque_dialog(cheque_modes, cash_modes) {
		const all_fieldnames = [].concat(
			cheque_modes.map(function (_, i) { return "chq_" + i; }),
			cash_modes.map(function (_, i) { return "csh_" + i; })
		);

		const fields = [
			{
				fieldname: "invoice_total",
				fieldtype: "Currency",
				label: __("Amount to Pay"),
				default: invoice_total,
				read_only: 1,
				options: "currency",
				precision: precision,
			},
			{ fieldtype: "Section Break", label: __("Cheque Details") },
			{
				fieldname: "cheque_date",
				fieldtype: "Date",
				label: __("Cheque Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{ fieldname: "cheque_no", fieldtype: "Data", label: __("Cheque No"), reqd: 1 },
		];

		function push_rows(list, prefix, label, first_gets_total) {
			if (!list.length) return;
			fields.push({ fieldtype: "Section Break", label: label });
			list.forEach(function (mode, idx) {
				fields.push(
					{ fieldtype: "Section Break", fieldname: prefix + "row_" + idx, label: "", hide_border: 1 },
					{
						fieldname: prefix + idx,
						fieldtype: "Currency",
						label: mode,
						default: first_gets_total && idx === 0 ? invoice_total : 0,
						options: "currency",
						precision: precision,
					},
					{ fieldtype: "Column Break" },
					{
						fieldtype: "Button",
						fieldname: "fill_" + prefix + idx,
						label: mode,
						click: (function (target) {
							return function () {
								all_fieldnames.forEach(function (fn) { d.set_value(fn, 0); });
								d.set_value(target, invoice_total);
							};
						})(prefix + idx)
					}
				);
			});
		}

		push_rows(cheque_modes, "chq_", __("Cheque Payments"), true);
		push_rows(cash_modes, "csh_", __("Other Payments"), false);

		function apply_and_close(vals, submit) {
			if (!vals) return;

			let cheque_total = 0, cash_total = 0;
			const cheque_payments = [], cash_payments = [];

			cheque_modes.forEach(function (mode, i) {
				const amt = flt(vals["chq_" + i]) || 0;
				if (amt > 0) { cheque_payments.push({ mode_of_payment: mode, amount: amt }); cheque_total += amt; }
			});
			cash_modes.forEach(function (mode, i) {
				const amt = flt(vals["csh_" + i]) || 0;
				if (amt > 0) { cash_payments.push({ mode_of_payment: mode, amount: amt }); cash_total += amt; }
			});

			if (!cheque_payments.length && !cash_payments.length) {
				frappe.msgprint({ title: __("Error"), message: __("Please enter at least one payment amount."), indicator: "red" });
				return;
			}

			const total_rounded = flt(cheque_total + cash_total, precision);
			if (total_rounded - invoice_total > 0.0001) {
				frappe.msgprint({
					title: __("Error"),
					message: __("Total payment {0} exceeds amount to pay {1}.", [
						format_currency(total_rounded, currency), format_currency(invoice_total, currency)]),
					indicator: "red",
				});
				return;
			}
			if (invoice_total - total_rounded > 0.0001) {
				frappe.msgprint({
					title: __("Incomplete"),
					message: __("{0} still to be allocated.", [format_currency(invoice_total - total_rounded, currency)]),
					indicator: "red",
				});
				return;
			}

			const cheque_date = vals.cheque_date;
			const cheque_no = (vals.cheque_no || "").trim();

			const finalize = function () {
				const actual_os = flt(Math.abs(flt(frm.doc.outstanding_amount || 0)), precision);
				if (actual_os > 0 && flt(total_rounded - actual_os) > 0.0001) {
					frappe.msgprint({
						title: __("Payment Error"),
						message: __("Payment total ({0}) exceeds outstanding amount ({1}). Please create the payment manually.", [
							format_currency(total_rounded, currency), format_currency(actual_os, currency)]),
						indicator: "red",
					});
					return;
				}
				d.hide();
				frappe.flags.aqrar_popup_showing = false;

				// cheque entries first, then cash, so they do not race on outstanding
				const create_cash = function () {
					if (!cash_payments.length) { frm.reload_doc(); return; }
					frappe.call({
						method: "aqrar_ext.api.sales_invoice.create_pos_payments_for_invoice",
						args: { sales_invoice: frm.doc.name, payments: JSON.stringify(cash_payments) },
						freeze: true,
						freeze_message: __("Creating payment..."),
						callback: function () {
							frappe.show_alert({ message: __("Payment Entries created."), indicator: "green" }, 5);
							frm.reload_doc();
						},
					});
				};

				if (cheque_payments.length) {
					frappe.call({
						method: "aqrar_ext.api.sales_invoice.create_pos_payments_for_invoice",
						args: {
							sales_invoice: frm.doc.name,
							payments: JSON.stringify(cheque_payments),
							cheque_date: cheque_date,
							cheque_no: cheque_no,
						},
						freeze: true,
						freeze_message: __("Creating cheque payment..."),
						callback: create_cash,
					});
				} else {
					create_cash();
				}
			};

			if (submit && frm.doc.docstatus === 0) {
				frappe.flags.aqrar_skip_payment_popup = true;
				frm.save("Submit").then(function () {
					if (frm.doc.docstatus !== 1) return;
					aqrar_open_invoice_print(frm);
					finalize();
				}).finally(function () {
					setTimeout(function () { delete frappe.flags.aqrar_skip_payment_popup; }, 500);
				});
			} else if (frm.doc.docstatus === 1) {
				finalize();
			} else {
				frappe.show_alert({ message: __("Invoice saved. Submit when ready to record the cheque payment."), indicator: "blue" }, 4);
			}
		}

		const d = new frappe.ui.Dialog({
			title: __("Cheque Payment"),
			fields: fields,
			primary_action_label: __("Save & Submit"),
			primary_action: function (vals) { if (vals) apply_and_close(vals, true); },
			secondary_action_label: __("Save"),
			secondary_action: function () {
				if (frm.doc.docstatus === 0) {
					d.hide();
					frappe.flags.aqrar_popup_showing = false;
					frappe.show_alert({ message: __("Invoice saved. Submit when ready to record the cheque payment."), indicator: "blue" }, 4);
					frm.reload_doc();
					return;
				}
				const vals = d.get_values();
				if (vals) apply_and_close(vals, false);
			},
			onhide: function () { frappe.flags.aqrar_popup_showing = false; },
		});

		d.show();

		frappe.utils.sleep(100).then(function () {
			d.$wrapper.find(".section-body").css({ display: "flex", alignItems: "flex-end" });
			all_fieldnames.forEach(function (fn, idx) {
				const field = d.fields_dict[fn];
				if (!field || !field.$wrapper) return;
				field.$wrapper.find("input").off("click.aqrar_chq").on("click.aqrar_chq", function () {
					let other = 0;
					all_fieldnames.forEach(function (ofn, oi) {
						if (oi !== idx) other += flt(d.get_value(ofn)) || 0;
					});
					d.set_value(fn, Math.max(0, flt(invoice_total - other)));
				});
			});
		});
	}
}
