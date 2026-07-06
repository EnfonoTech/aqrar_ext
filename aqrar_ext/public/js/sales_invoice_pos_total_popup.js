// aqrar_ext: Payment popup after save — dynamic mode, amount-based flow

frappe.ui.form.on("Sales Invoice", {
	after_save: function (frm) {
		if (frappe.flags.aqrar_skip_payment_popup) return;
		if (frappe.flags.aqrar_payment_popup_showing) return;
		if (frm.doc.docstatus !== 0) return;
		if (!frm.doc.name || String(frm.doc.name).startsWith("new-")) return;
		if (flt(frm.doc.grand_total) <= 0) return;

		frappe.call({
			method: "aqrar_ext.api.sales_invoice.get_payment_modes_with_account",
			args: { company: frm.doc.company },
			callback: function (res) {
				const modes = res.message || [];
				if (!modes.length) {
					frappe.msgprint(__("No payment modes configured for this company."));
					return;
				}
				aqrar_show_payment_popup(frm, modes);
			},
		});
	},
});

function aqrar_show_payment_popup(frm, payment_modes) {
	if (frappe.flags.aqrar_payment_popup_showing) return;
	frappe.flags.aqrar_payment_popup_showing = true;

	const invoice_total = flt(frm.doc.rounded_total || frm.doc.grand_total || 0);
	const currency = frm.doc.currency || "";
	const mode_options = [...payment_modes, "Credit"];

	const d = new frappe.ui.Dialog({
		title: __("Payment"),
		fields: [
			{
				fieldname: "invoice_total",
				fieldtype: "Currency",
				label: __("Invoice Total"),
				default: invoice_total,
				read_only: 1,
				options: currency,
			},
			{
				fieldname: "payment_mode",
				fieldtype: "Select",
				label: __("Payment Mode"),
				options: mode_options.join("\n"),
				default: payment_modes[0] || "",
				reqd: 1,
				onchange: function () {
					const amount_field = d.get_field("amount");
					if (this.value === "Credit") {
						d.set_value("amount", 0);
						amount_field.df.read_only = 1;
					} else {
						amount_field.df.read_only = 0;
						if (flt(d.get_value("amount")) === 0) {
							d.set_value("amount", invoice_total);
						}
					}
					amount_field.refresh();
				},
			},
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				default: invoice_total,
				options: currency,
			},
		],
		primary_action_label: __("Save & Submit"),
		secondary_action_label: __("Save Only"),
		primary_action: function (vals) {
			const mode = vals.payment_mode;
			const amount = mode === "Credit" ? 0 : flt(vals.amount);

			if (amount < 0) {
				frappe.msgprint(__("Amount cannot be negative."));
				return;
			}
			if (amount > invoice_total + 0.5) {
				frappe.msgprint(__("Amount cannot exceed Invoice Total."));
				return;
			}

			d.hide();
			frappe.flags.aqrar_payment_popup_showing = false;
			frappe.flags.aqrar_skip_payment_popup = true;

			frm.save("Submit")
				.then(function () {
					if (frm.doc.docstatus !== 1) return;

					if (amount > 0) {
						frappe.call({
							method: "aqrar_ext.api.sales_invoice.create_pos_payments_for_invoice",
							args: {
								sales_invoice: frm.doc.name,
								payments: JSON.stringify([
									{ mode_of_payment: mode, amount: amount },
								]),
							},
							freeze: true,
							freeze_message: __("Creating Payment Entry..."),
							callback: function (res) {
								const created = (res && res.message) || [];
								if (created.length) {
									frappe.show_alert(
										{
											message: __("Payment Entry {0} created", [created[0]]),
											indicator: "green",
										},
										5
									);
								}
								frm.reload_doc();
							},
							error: function () {
								frappe.msgprint(
									__(
										"Invoice submitted but Payment Entry could not be created. Please create it manually."
									)
								);
								frm.reload_doc();
							},
						});
					} else {
						// Amount = 0, submit as credit — no PE
						frm.reload_doc();
					}
				})
				.catch(function () {
					frappe.msgprint({
						title: __("Submit Failed"),
						message: __("Could not submit the invoice. Please check for errors."),
						indicator: "red",
					});
				})
				.finally(function () {
					delete frappe.flags.aqrar_skip_payment_popup;
					frappe.flags.aqrar_payment_popup_showing = false;
				});
		},
		secondary_action: function () {
			frappe.flags.aqrar_payment_popup_showing = false;
			d.hide();
		},
		onhide: function () {
			frappe.flags.aqrar_payment_popup_showing = false;
		},
	});

	d.show();
}
