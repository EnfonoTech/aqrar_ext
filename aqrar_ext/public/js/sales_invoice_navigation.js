frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;

		frm.page.add_inner_button(__("Prev"), function () {
			_navigate(frm, "prev");
		});

		frm.page.add_inner_button(__("Next"), function () {
			_navigate(frm, "next");
		});

		_bind_keys(frm);
	},
});

function _bind_keys(frm) {
	$(document).off("keydown.si_nav").on("keydown.si_nav", function (e) {
		if (frappe.get_route_str() !== "Form/Sales Invoice/" + frm.doc.name) return;
		if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
		if (e.key === "ArrowLeft" && !e.altKey && !e.ctrlKey) {
			e.preventDefault();
			_navigate(frm, "prev");
		}
		if (e.key === "ArrowRight" && !e.altKey && !e.ctrlKey) {
			e.preventDefault();
			_navigate(frm, "next");
		}
	});
}

function _navigate(frm, direction) {
	var ctx = _get_list_context();

	frappe.call({
		method: "aqrar_ext.api.navigation.get_sibling",
		args: {
			doctype: frm.doc.doctype,
			docname: frm.doc.name,
			direction: direction,
			list_filters: ctx.filters,
			order_by: ctx.order_by,
		},
		callback: function (r) {
			if (r.message) {
				frappe.set_route("Form", frm.doc.doctype, r.message);
			} else {
				frappe.show_alert({
					message: direction === "next" ? __("No next document") : __("No previous document"),
					indicator: "blue",
				});
			}
		},
	});
}

function _get_list_context() {
	try {
		var raw = localStorage.getItem("Sales Invoice_list_view");
		if (raw) {
			var state = JSON.parse(raw);
			return { filters: state.filters || [], order_by: state.sort_by || null };
		}
	} catch (e) {}
	return { filters: [], order_by: null };
}
