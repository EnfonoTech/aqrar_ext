// aqrar_ext: POS payment popup + create Payment Entry on submit

frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		const should_open_popup_before_submit = function () {
			return (
				!frappe.flags.aqrar_skip_payment_popup &&
				!frappe.flags.aqrar_payment_popup_showing &&
				frm.doc &&
				frm.doc.docstatus === 0 &&
				frm.doc.custom_payment_mode === "Cash" &&
				flt(frm.doc.grand_total) > 0 &&
				frm.doc.name &&
				!String(frm.doc.name).startsWith("new-")
			);
		};
		if (frm._aqrar_save_wrapped) return;
		frm._aqrar_save_wrapped = true;
		const orig = frm.save.bind(frm);
		frm.save = function (save_action, callback, btn, on_error) {
			frappe.flags._aqrar_save_action = save_action || "Save";
			if (save_action === "Submit" && should_open_popup_before_submit()) {
				aqrar_show_pos_total_popup(frm);
				return Promise.resolve();
			}

			return orig(save_action, callback, btn, on_error).finally(function () {
				delete frappe.flags._aqrar_save_action;
			});
		};

		// Frappe toolbar submit can call savesubmit() directly.
		// Intercept it too so popup always appears before submit.
		if (!frm._aqrar_savesubmit_wrapped && frm.savesubmit) {
			frm._aqrar_savesubmit_wrapped = true;
			const orig_savesubmit = frm.savesubmit.bind(frm);
			frm.savesubmit = function (btn, callback, on_error) {
				if (should_open_popup_before_submit()) {
					aqrar_show_pos_total_popup(frm);
					return Promise.resolve();
				}
				// Credit: direct submit (no payment popup)
				return orig_savesubmit(btn, callback, on_error);
			};
		}
	},
	after_save: function (frm) {
		// Popup on Save also (but never when the save is triggered from inside this popup)
		if (frappe.flags.aqrar_skip_payment_popup) return;

		// Prevent popup if already showing
		if (frappe.flags.aqrar_payment_popup_showing) return;

		// Only for draft Sales Invoice
		if (frm.doc.docstatus !== 0) return;
		if (frm.doc.custom_payment_mode !== "Cash") return;

		// Validate required fields
		if (!frm.doc.grand_total || frm.doc.grand_total <= 0) return;
		if (!frm.doc.name || String(frm.doc.name).startsWith("new-")) return;

		// If POS Profile exists, respect its disable flag; else show popup anyway
		if (frm.doc.pos_profile) {
			frappe.db.get_value(
				"POS Profile",
				frm.doc.pos_profile,
				"disable_grand_total_to_default_mop",
				function (r) {
					if (r && r.message === 1) return;
					aqrar_show_pos_total_popup(frm);
				}
			);
		} else {
			aqrar_show_pos_total_popup(frm);
		}
	},
	// Credit — ask submit vs save only when user clicks Save (not Submit)
	before_save: function (frm) {
		if (!frm.doc.custom_payment_mode || frm.doc.custom_payment_mode !== "Credit") return;
		if (frm.doc.docstatus !== 0) return;
		if (frappe.flags._aqrar_save_action === "Submit") return;
		if (frm._aqrar_asked_to_submit) return;

		frm._aqrar_asked_to_submit = true;
		frappe.validated = false;

		frappe.confirm(
			__("Do you want to Submit this Sales Invoice now?"),
			function () {
				frm.save("Submit").then(function () {
					frm._aqrar_asked_to_submit = false;
					frm.reload_doc();
				});
			},
			function () {
				frm.save().then(function () {
					frm._aqrar_asked_to_submit = false;
				});
			}
		);
	},
});

function aqrar_show_pos_total_popup(frm) {
	// Prevent multiple popups
	if (frappe.flags.aqrar_payment_popup_showing) return;

	// Validate form state
	if (!frm || !frm.doc) {
		return;
	}

	frappe.flags.aqrar_payment_popup_showing = true;

	function do_show_popup() {
		if (frm.doc.pos_profile || !frm.doc.payments || frm.doc.payments.length === 0) {
			if (!frm.doc.pos_profile) {
				frappe.call({
					method: "aqrar_ext.api.sales_invoice_payment.get_payment_modes_with_account",
					args: { company: frm.doc.company },
					callback: function (res) {
						const modes = res.message || [];
						if (!modes.length) {
							frappe.flags.aqrar_payment_popup_showing = false;
							frappe.msgprint(
								__("No enabled payment modes with a default account for this company.")
							);
							return;
						}

						frm.clear_table("payments");
						modes.forEach(function (mode) {
							const row = frm.add_child("payments");
							row.mode_of_payment = mode;
						});
						frm.refresh_field("payments");

						frappe.call({
							doc: frm.doc,
							method: "set_account_for_mode_of_payment",
							callback: function () {
								frm.refresh_field("payments");
								aqrar_render_dialog(frm);
							},
							error: function () {
								frappe.flags.aqrar_payment_popup_showing = false;
								frappe.msgprint(__("Error loading payment accounts. Please try again."));
							},
						});
					},
					error: function () {
						frappe.flags.aqrar_payment_popup_showing = false;
						frappe.msgprint(__("Error loading payment modes. Please try again."));
					},
				});
				return;
			}
			frappe.call({
				method: "frappe.client.get",
				args: { doctype: "POS Profile", name: frm.doc.pos_profile },
				callback: function (r) {
					if (r.message && r.message.payments && r.message.payments.length > 0) {
						const profile_payments = r.message.payments;
						const mode_list = profile_payments.map((p) => p.mode_of_payment);
						const default_by_mode = {};
						profile_payments.forEach((p) => (default_by_mode[p.mode_of_payment] = p.default));

						frappe.call({
							method: "aqrar_ext.api.sales_invoice_payment.get_payment_modes_with_account",
							args: { company: frm.doc.company, mode_list: mode_list },
							callback: function (res) {
								const valid_modes = res.message || [];
								if (!valid_modes.length) {
									frappe.flags.aqrar_payment_popup_showing = false;
									frappe.msgprint(
										__("No enabled payment modes with a default account for this company.")
									);
									return;
								}

								frm.clear_table("payments");
								valid_modes.forEach(function (mode) {
									const row = frm.add_child("payments");
									row.mode_of_payment = mode;
									row.default = default_by_mode[mode] || 0;
								});
								frm.refresh_field("payments");

								frappe.call({
									doc: frm.doc,
									method: "set_account_for_mode_of_payment",
									callback: function () {
										frm.refresh_field("payments");
										aqrar_render_dialog(frm);
									},
									error: function () {
										frappe.flags.aqrar_payment_popup_showing = false;
										frappe.msgprint(__("Error loading payment accounts. Please try again."));
									},
								});
							},
							error: function () {
								frappe.flags.aqrar_payment_popup_showing = false;
								frappe.msgprint(__("Error loading payment modes. Please try again."));
							},
						});
					} else {
						frappe.flags.aqrar_payment_popup_showing = false;
						frappe.msgprint(__("Add payment modes in POS Profile first"));
					}
				},
				error: function () {
					frappe.flags.aqrar_payment_popup_showing = false;
					frappe.msgprint(__("Error loading POS Profile. Please try again."));
				},
			});
		} else {
			aqrar_render_dialog(frm);
		}
	}

	do_show_popup();
}

function aqrar_render_dialog(frm) {
	// Validate form state
	if (!frm || !frm.doc) {
		frappe.flags.aqrar_payment_popup_showing = false;
		return;
	}

	const payments = frm.doc.payments || [];
	if (payments.length === 0) {
		frappe.flags.aqrar_payment_popup_showing = false;
		return;
	}

	const invoice_total = flt(frm.doc.rounded_total || frm.doc.grand_total || 0);
	const currency = frm.doc.currency || "";

	// Validate invoice total
	if (invoice_total <= 0) {
		frappe.flags.aqrar_payment_popup_showing = false;
		frappe.msgprint(__("Invoice total must be greater than zero."));
		return;
	}

	const fields = [
		{
			fieldname: "invoice_total",
			fieldtype: "Currency",
			label: __("Invoice Total"),
			default: invoice_total,
			read_only: 1,
			options: currency,
		},
		{ fieldtype: "Section Break", label: __("Enter Payment Amounts") },
	];

	payments.forEach(function (payment, idx) {
		const mode = payment.mode_of_payment || "Payment " + (idx + 1);
		fields.push(
			{
				fieldtype: "Section Break",
				fieldname: "row_" + idx,
				label: "",
				hide_border: 1,
				collapsible: 0,
			},
			{
				fieldname: "pay_" + idx,
				fieldtype: "Currency",
				label: mode,
				default: payment.amount || 0,
				options: currency,
			},
			{ fieldtype: "Column Break", fieldname: "cb_" + idx },
			{
				fieldtype: "Button",
				fieldname: "fill_" + idx,
				label: mode,
				click: function () {
					payments.forEach(function (_, i) {
						d.set_value("pay_" + i, i === idx ? invoice_total : 0);
					});
				},
			}
		);
	});

	function apply_payments_and_close(vals, submit) {
		// Prevent multiple simultaneous saves
		if (frappe.flags.aqrar_payment_popup_saving) {
			frappe.msgprint({
				title: __("Please Wait"),
				message: __("Saving in progress. Please wait..."),
				indicator: "orange",
			});
			return;
		}

		// Validate form state
		if (!frm || !frm.doc || frm.doc.docstatus !== 0) {
			frappe.msgprint({
				title: __("Error"),
				message: __("Cannot update payments. Form is not in draft state."),
				indicator: "red",
			});
			return;
		}

		// Validate inputs
		if (!vals) {
			frappe.msgprint({
				title: __("Error"),
				message: __("Please enter payment amounts."),
				indicator: "red",
			});
			return;
		}

		let total = 0;
		// First validate total + collect payload for Payment Entry creation
		const payments_payload = [];
		payments.forEach(function (p, i) {
			const amt = flt(vals["pay_" + i]) || 0;
			total += amt;
			if (amt > 0) {
				payments_payload.push({ mode_of_payment: p.mode_of_payment, amount: amt });
			}
		});

		if (total < invoice_total) {
			frappe.msgprint({
				title: __("Incomplete"),
				message: __("{0} still to be allocated", [format_currency(invoice_total - total, currency)]),
				indicator: "red",
			});
			return;
		}

		if (total - invoice_total > 0.5) {
			frappe.msgprint({
				title: __("Error"),
				message: __(
					"Total payment amount {0} cannot be greater than invoice total {1}.",
					[format_currency(total, currency), format_currency(invoice_total, currency)]
				),
				indicator: "red",
			});
			return;
		}

		// Ensure form payments exist and match
		const form_payments = frm.doc.payments || [];
		if (form_payments.length === 0) {
			frappe.msgprint({
				title: __("Error"),
				message: __("No payment methods found. Please refresh the form."),
				indicator: "red",
			});
			return;
		}

		// Ensure conversion_rate is valid
		const conversion_rate = flt(frm.doc.conversion_rate) || 1;

		// Helper function for precision
		const get_precision = function (fieldname, doc) {
			try {
				return precision(fieldname, doc) || 2;
			} catch (e) {
				return 2;
			}
		};

		// Update payments with robust matching - update ALL payments (including zero amounts)
		let update_count = 0;
		payments.forEach(function (p, i) {
			const amt = flt(vals["pay_" + i]) || 0;
			const base_amt = flt(amt * conversion_rate, get_precision("base_amount", p));

			// Try multiple matching strategies for reliability
			let form_payment = null;

			// Strategy 1: Match by mode_of_payment
			if (p.mode_of_payment) {
				form_payment = form_payments.find((fp) => fp.mode_of_payment === p.mode_of_payment);
			}

			// Strategy 2: Match by index if same length
			if (!form_payment && i < form_payments.length && payments.length === form_payments.length) {
				form_payment = form_payments[i];
			}

			// Strategy 3: Match by idx if available
			if (!form_payment && p.idx) {
				form_payment = form_payments.find((fp) => fp.idx === p.idx);
			}

			// Strategy 4: Match by name if available
			if (!form_payment && p.name) {
				form_payment = form_payments.find((fp) => fp.name === p.name);
			}

			// Update if match found - update ALL payments including zero amounts
			if (form_payment) {
				form_payment.amount = amt;
				form_payment.base_amount = base_amt;
				update_count++;
			}
		});

		// Validate that we updated at least one payment
		if (update_count === 0) {
			frappe.msgprint({
				title: __("Error"),
				message: __("Could not match payments. Please refresh the form and try again."),
				indicator: "red",
			});
			return;
		}

		// Verify payments were updated
		const updated_payments = frm.doc.payments.filter((p) => flt(p.amount) > 0);
		if (updated_payments.length === 0) {
			frappe.msgprint({
				title: __("Error"),
				message: __("No payment amounts were set. Please try again."),
				indicator: "red",
			});
			return;
		}

		// Ensure form recognizes payments as changed
		if (frm.local_doclist && frm.local_doclist["Sales Invoice Payment"]) {
			frm.doc.payments.forEach(function (payment) {
				const doclist_item = frm.local_doclist["Sales Invoice Payment"].find(
					(item) => item.name === payment.name || item.idx === payment.idx
				);
				if (doclist_item) {
					doclist_item.amount = payment.amount;
					doclist_item.base_amount = payment.base_amount;
				}
			});
		}

		// Mark form as dirty to ensure changes are saved
		frm.dirty();

		// Refresh payments field to update UI before saving
		frm.refresh_field("payments");

		// Close dialog before saving
		d.hide();
		frappe.flags.aqrar_skip_payment_popup = true;
		frappe.flags.aqrar_payment_popup_showing = false;
		frappe.flags.aqrar_payment_popup_saving = true;

		// Use save with "Submit" action instead of savesubmit
		const save_action = submit ? "Submit" : "Save";

		// Delay to ensure refresh_field completes and form processes updates
		setTimeout(function () {
			// Double-check payments are in form doc before saving
			if (!frm.doc.payments || frm.doc.payments.length === 0) {
				frappe.msgprint({
					title: __("Error"),
					message: __("Payments were not updated. Please try again."),
					indicator: "red",
				});
				delete frappe.flags.aqrar_skip_payment_popup;
				delete frappe.flags.aqrar_payment_popup_saving;
				return;
			}

			// Verify payments have amounts
			const total_payment = frm.doc.payments.reduce((sum, p) => sum + flt(p.amount), 0);
			if (total_payment <= 0) {
				frappe.msgprint({
					title: __("Error"),
					message: __("Total payment amount must be greater than zero."),
					indicator: "red",
				});
				delete frappe.flags.aqrar_skip_payment_popup;
				delete frappe.flags.aqrar_payment_popup_saving;
				return;
			}

			// Submit as non-POS so the payments child table does NOT auto-settle the
			// invoice at submit. Outstanding stays at grand_total so the backend
			// Payment Entries created next actually close the invoice.
			if (submit) {
				frm.doc.is_pos = 0;
				frm.clear_table("payments");
				frm.refresh_field("is_pos");
				frm.refresh_field("payments");
			}

			// Save - payments are already updated in frm.doc.payments
			frm.save(save_action)
				.then(function (r) {
					// If user submitted, create Payment Entries from the popup amounts
					if (submit && frm.doc.docstatus === 1) {
						frappe.call({
							method: "aqrar_ext.api.sales_invoice_payment.create_pos_payments_for_invoice",
							args: {
								sales_invoice: frm.doc.name,
								payments: JSON.stringify(payments_payload),
							},
							freeze: true,
							freeze_message: __("Creating Payment Entries..."),
							callback: function (res) {
								const created = (res && res.message) || [];
								if (created.length) {
									frappe.show_alert(
										{
											message: __("Created {0} Payment Entries", [created.length]),
											indicator: "green",
										},
										5
									);
								}
								frm.reload_doc();
							},
							error: function () {
								frappe.msgprint({
									title: __("Error"),
									message: __("Could not create Payment Entries. Please check Mode of Payment accounts."),
									indicator: "red",
								});
								frm.reload_doc();
							},
						});
						return;
					}

					// Submit was requested but docstatus is still 0 — submit failed
					if (submit && frm.doc.docstatus !== 1) {
						frappe.msgprint({
							title: __("Submit Failed"),
							message: __("The invoice could not be submitted. Please check for validation errors and try again."),
							indicator: "orange",
						});
						frm.reload_doc();
						return;
					}

					// After save (without submit), refresh payments field to show updated values
					setTimeout(function () {
						frm.refresh_field("payments");

						if (submit) {
							setTimeout(function () {
								frm.reload_doc();
							}, 200);
						}
					}, 100);
				})
				.catch(function (err) {
					frappe.msgprint({
						title: __("Error"),
						message: __("Failed to save invoice: {0}", [err.message || err]),
						indicator: "red",
					});
				})
				.finally(function () {
					setTimeout(function () {
						delete frappe.flags.aqrar_skip_payment_popup;
						delete frappe.flags.aqrar_payment_popup_saving;
					}, 500);
				});
		}, 300);
	}

	const d = new frappe.ui.Dialog({
		title: __("Enter Payment Amounts"),
		fields: fields,
		primary_action_label: __("Save & Submit"),
		primary_action: function (vals) {
			apply_payments_and_close(vals, true);
		},
		secondary_action_label: __("Save"),
		secondary_action: function () {
			const vals = d.get_values();
			if (vals) apply_payments_and_close(vals, false);
		},
		onhide: function () {
			frappe.flags.aqrar_payment_popup_showing = false;
		},
	});

	d.show();

	// Align button with input (same level) and field click handler
	frappe.utils.sleep(100).then(function () {
		d.$wrapper.find(".section-body").css({
			display: "flex",
			alignItems: "flex-end",
		});

		// Field click: fill with balance only (invoice_total - sum of others)
		payments.forEach(function (_, idx) {
			const field = d.fields_dict["pay_" + idx];
			if (!field || !field.$wrapper) return;
			const $input = field.$wrapper.find("input");
			$input.off("click.aqrar_fill_balance").on("click.aqrar_fill_balance", function () {
				let other = 0;
				payments.forEach(function (__, i) {
					if (i !== idx) other += flt(d.get_value("pay_" + i)) || 0;
				});
				d.set_value("pay_" + idx, Math.max(0, flt(invoice_total - other, 2)));
			});
		});
	});
}
