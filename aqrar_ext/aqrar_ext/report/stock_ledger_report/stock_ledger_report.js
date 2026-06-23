frappe.query_reports["Stock Ledger Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company") || frappe.defaults.get_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "MultiSelectList",
			options: "Warehouse",
			get_data: function (txt) {
				return frappe.db.get_link_options("Warehouse", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "MultiSelectList",
			options: "Item",
			get_data: async function (txt) {
				let { message: data } = await frappe.call({
					method: "erpnext.controllers.queries.item_query",
					args: { doctype: "Item", txt: txt, searchfield: "name", start: 0, page_len: 10, filters: {}, as_dict: 1 },
				});
				return (data || []).map(function (d) {
					return { value: d.name, description: Object.values(d).slice(1) };
				});
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options: "Brand",
		},
		{
			fieldname: "batch_no",
			label: __("Batch No"),
			fieldtype: "Link",
			options: "Batch",
		},
		{
			fieldname: "voucher_no",
			label: __("Voucher #"),
			fieldtype: "Data",
		},
		{
			fieldname: "voucher_type",
			label: __("Transaction Type"),
			fieldtype: "Select",
			options: ["All", "Purchase Only", "Sale Only", "Transfer Only", "Stock Entry Only"],
			default: "All",
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "include_uom",
			label: __("Include UOM"),
			fieldtype: "Link",
			options: "UOM",
		},
		{
			fieldname: "valuation_field_type",
			label: __("Valuation Field Type"),
			fieldtype: "Select",
			options: "Currency\nFloat",
			default: "Currency",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "qty_in" && flt(value) > 0) {
			return "<span style='color:var(--green-600);font-weight:600'>" + value + "</span>";
		}
		if (column.fieldname === "qty_out" && flt(value) > 0) {
			return "<span style='color:var(--red-600);font-weight:600'>" + value + "</span>";
		}
		if (column.fieldname === "qty_after_transaction") {
			var color = flt(value) >= 0 ? "var(--blue-600)" : "var(--red-600)";
			return "<span style='color:" + color + ";font-weight:600'>" + value + "</span>";
		}
		return default_formatter(value, row, column, data);
	},

	onload: function (report) {
		report.page.add_inner_button(__("View Stock Balance"), function () {
			frappe.set_route("query-report", "Stock Balance", report.get_values());
		});
		_render_special_analysis_links(report);
	},
};

function _render_special_analysis_links(report) {
	var custom_reports = (window.aqrar_ext || {}).stock_ledger_special_reports || [];
	if (!custom_reports.length) return;

	var $wrapper = $(report.wrapper).find(".page-form");
	if ($wrapper.find(".aqrar-special-analysis").length) return;

	var $links = $(
		'<div class="aqrar-special-analysis" style="padding:8px 0 4px;">' +
			'<span style="font-weight:600;margin-right:8px;">' + __("Special Analysis:") + "</span>" +
		"</div>"
	);

	custom_reports.forEach(function (r) {
		$links.append(
			$('<a class="btn btn-xs btn-default" style="margin-right:6px;">')
				.text(__(r.label))
				.on("click", function () {
					frappe.set_route("query-report", r.report_name);
				})
		);
	});

	$wrapper.append($links);
}
