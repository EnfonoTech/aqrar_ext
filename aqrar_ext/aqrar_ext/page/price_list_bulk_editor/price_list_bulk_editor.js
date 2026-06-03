frappe.pages["price-list-bulk-editor"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Price List Bulk Editor"),
		single_column: true,
	});

	page.main.css("padding", "0");

	var columns = [];
	var data = [];
	var current_pls = [];

	var chrome_html = `
	<div class="ple-card">
		<div class="ple-card-body">
			<div class="ple-filters">
				<div class="ple-field" id="ple-f-item-code"></div>
				<div class="ple-field" id="ple-f-item-group"></div>
				<div class="ple-field" id="ple-f-plist"></div>
				<div class="ple-field" id="ple-f-cost-center"></div>
				<div class="ple-actions">
					<button class="btn btn-default btn-sm" id="ple-btn-refresh">${__("Refresh")}</button>
				</div>
			</div>
		</div>
	</div>
	<div class="ple-status" id="ple-status"></div>
	<div class="ple-table-shell" id="ple-table-shell">
		<div class="ple-empty" id="ple-empty">
			<p class="ple-empty-title">${__("Loading…")}</p>
			<p class="ple-empty-sub">${__("Click a cell to edit. Press Enter or Tab to save.")}</p>
		</div>
	</div>
	`;
	$(chrome_html).appendTo(page.main);

	var item_code_field = frappe.ui.form.make_control({
		parent: $("#ple-f-item-code"),
		df: {
			fieldname: "item_code", label: __("Item Code"), fieldtype: "Link", options: "Item",
			change: function () { load_data(); }
		},
		render_input: true,
	});

	var item_group_field = frappe.ui.form.make_control({
		parent: $("#ple-f-item-group"),
		df: {
			fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group",
			change: function () { load_data(); }
		},
		render_input: true,
	});

	var price_list_field = frappe.ui.form.make_control({
		parent: $("#ple-f-plist"),
		df: {
			fieldname: "price_list", label: __("Price List"), fieldtype: "Link", options: "Price List",
			change: function () { load_data(); }
		},
		render_input: true,
	});

	var cost_center_field = frappe.ui.form.make_control({
		parent: $("#ple-f-cost-center"),
		df: {
			fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link", options: "Cost Center",
			change: function () { load_price_lists_and_data(); }
		},
		render_input: true,
	});

	$("#ple-btn-refresh").on("click", load_data);

	function load_price_lists_and_data() {
		var $btn = $("#ple-btn-refresh").prop("disabled", true);
		frappe.call({
			method: "aqrar_ext.aqrar_ext.page.price_list_bulk_editor.price_list_bulk_editor.get_selling_price_lists",
			args: { cost_center: cost_center_field.get_value() || "" },
			callback: function (r) {
				current_pls = (r.message || []).map(function (p) { return p.name; });
				$btn.prop("disabled", false);
				load_data();
			},
			error: function () {
				$btn.prop("disabled", false);
				frappe.show_alert({
					message: __("Failed to load price lists."),
					indicator: "red",
				});
			},
		});
	}

	function load_data() {
		var selected_pl = price_list_field.get_value();
		var pls = selected_pl ? [selected_pl] : current_pls;
		if (!pls.length) {
			if (!current_pls.length) {
				show_empty(__("Loading price lists…"));
			} else {
				show_empty(__("No selling price lists found for this cost center."));
			}
			return;
		}
		$("#ple-empty").show().find(".ple-empty-title").text(__("Loading…"));
		$("#ple-table-shell").find(".ple-scroll, table").remove();
		$("#ple-btn-refresh").prop("disabled", true);

		frappe.call({
			method: "aqrar_ext.aqrar_ext.page.price_list_bulk_editor.price_list_bulk_editor.get_item_price_matrix",
			args: {
				item_group: item_group_field.get_value() || "",
				item_code: item_code_field.get_value() || "",
				price_lists: pls,
				cost_center: cost_center_field.get_value() || "",
			},
			callback: function (r) {
				$("#ple-btn-refresh").prop("disabled", false);
				var msg = r.message;
				if (!msg || !msg.data.length) {
					show_empty(__("No items found."));
					return;
				}
				columns = msg.columns;
				data = msg.data;
				build_table(msg.item_count, msg.price_lists.length);
			},
			error: function () {
				$("#ple-btn-refresh").prop("disabled", false);
				frappe.show_alert({
					message: __("Failed to load data."),
					indicator: "red",
				});
			},
		});
	}

	function build_table(item_count, pl_count) {
		$("#ple-empty").hide();
		var $shell = $("#ple-table-shell");
		$shell.find(".ple-scroll, table").remove();

		var c = columns;
		var d = data;

		var h = '<div class="ple-scroll"><table class="ple-table"><thead><tr>';
		c.forEach(function (col, ci) {
			var sticky = ci < 3 ? " ple-col-sticky" : "";
			var cls = (col.editable ? "ple-th-price" : "ple-th-fixed") + sticky;
			h += '<th class="' + cls + '" style="min-width:' + (col.width || 120) + 'px">' + col.name + '</th>';
		});
		h += '</tr></thead><tbody>';

		d.forEach(function (row, ri) {
			h += '<tr>';
			row.forEach(function (cell, ci) {
				var sticky_cls = ci < 3 ? " ple-col-sticky" : "";
				if (!c[ci].editable) {
					h += '<td class="' + sticky_cls + '">' + frappe.utils.escape_html(String(cell || "")) + '</td>';
				} else {
					var info = cell && typeof cell === "object" ? cell : {};
					var rate = info.rate != null ? info.rate : "";
					var minr = info.min_rate != null ? info.min_rate : "";
					h += '<td class="ple-edit' + sticky_cls + '" data-ri="' + ri + '" data-ci="' + ci + '">';
					h += '<div class="ple-cell-stack">';
					h += '<input type="text" inputmode="decimal" class="ple-inp-rate" value="' + rate + '" placeholder="' + __("Rate") + '">';
					h += '<input type="text" inputmode="decimal" class="ple-inp-min"  value="' + minr + '" placeholder="' + __("Min") + '">';
					h += '</div>';
					h += '</td>';
				}
			});
			h += '</tr>';
		});
		h += '</tbody></table></div>';
		$shell.prepend(h);

		$("#ple-status").html(
			'<div class="ple-status-bar">' +
			'<span class="ple-badge">' + item_count + ' ' + __("items") + '</span>' +
			'<span class="ple-badge">' + pl_count + ' ' + __("price lists") + '</span>' +
			'<span class="ple-hint">' + __("Edit then Enter / Tab to save.") + '</span>' +
			'</div>'
		);

		$shell.find(".ple-inp-min, .ple-inp-rate").off("blur keydown").on("blur", function () {
			save_cell($(this).closest("td"));
		}).on("keydown", function (e) {
			if (e.key === "Enter") {
				e.preventDefault();
				$(this).blur();
			}
		});
	}

	function save_cell($td) {
		if ($td.hasClass("ple-saving")) return;

		var ri = parseInt($td.attr("data-ri"));
		var ci = parseInt($td.attr("data-ci"));
		if (isNaN(ri) || isNaN(ci)) return;

		var row = data[ri];
		var col = columns[ci];

		var $min_inp  = $td.find(".ple-inp-min");
		var $rate_inp = $td.find(".ple-inp-rate");

		var old_info = row[ci] && typeof row[ci] === "object" ? row[ci] : {};
		var old_rate = parseFloat(old_info.rate) || 0;
		var old_min  = parseFloat(old_info.min_rate) || 0;

		var new_rate = parseFloat($rate_inp.val().trim());
		var new_min  = parseFloat($min_inp.val().trim());
		if (isNaN(new_rate) || new_rate < 0) { $rate_inp.val(old_rate || ""); return; }
		if (isNaN(new_min)  || new_min  < 0) { $min_inp.val(old_min || "");   return; }
		if (new_rate === old_rate && new_min === old_min) return;

		$td.addClass("ple-saving");

		frappe.call({
			method: "aqrar_ext.aqrar_ext.page.price_list_bulk_editor.price_list_bulk_editor.save_cell",
			args: {
				item_code: row[0],
				price_list: col.price_list,
				uom: row[2],
				rate: new_rate,
				min_rate: new_min,
			},
			callback: function (r) {
				$td.removeClass("ple-saving");
				if (r.message) {
					row[ci] = { rate: new_rate, min_rate: new_min, item_price_name: r.message.name, uom: row[2] };
					$td.addClass("ple-saved");
					setTimeout(function () { $td.removeClass("ple-saved"); }, 900);
					frappe.show_alert({
						message: r.message.action === "updated"
							? __("Updated") + ": " + row[0] + " → " + col.price_list
							: __("Created") + ": " + row[0] + " → " + col.price_list,
						indicator: "green",
					});
				}
			},
			error: function () {
				$td.removeClass("ple-saving").addClass("ple-error");
				setTimeout(function () { $td.removeClass("ple-error"); }, 1500);
				frappe.show_alert({
					message: __("Failed to save") + ": " + row[0] + " → " + col.price_list,
					indicator: "red",
				});
			},
		});
	}

	function show_empty(msg) {
		$("#ple-status").empty();
		$("#ple-table-shell").find(".ple-scroll, table").remove();
		$("#ple-empty").show().find(".ple-empty-title").text(msg || __("No items found."));
	}

	load_price_lists_and_data();
};
