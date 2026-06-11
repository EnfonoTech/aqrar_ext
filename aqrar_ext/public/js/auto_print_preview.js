frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (!frm.doc.__islocal) init_or_refresh_preview(frm);
    },
    after_save: function (frm) {
        init_or_refresh_preview(frm);
    },
});

frappe.ui.form.on("Quotation", {
    refresh: function (frm) {
        if (!frm.doc.__islocal) init_or_refresh_preview(frm);
    },
    after_save: function (frm) {
        init_or_refresh_preview(frm);
    },
});

frappe.ui.form.on("Custom Quote", {
    refresh: function (frm) {
        if (!frm.doc.__islocal) init_or_refresh_preview(frm);
    },
    after_save: function (frm) {
        init_or_refresh_preview(frm);
    },
});

// Cache print formats per doctype so we don't re-fetch on every save
var print_format_cache = {};

function get_print_formats(doctype, callback) {
    if (print_format_cache[doctype]) {
        callback(print_format_cache[doctype]);
        return;
    }
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Print Format",
            filters: { doc_type: doctype, disabled: 0 },
            fields: ["name"],
            order_by: "name",
        },
        callback: function (r) {
            var formats = (r.message || []).map(function (f) { return f.name; });
            if (formats.indexOf("Standard") === -1) formats.unshift("Standard");
            // Prefer Aqrar print format for Sales Invoice
            if (doctype === "Sales Invoice") {
                var aqrar_idx = formats.indexOf("Sales Invoice Aqrar");
                if (aqrar_idx > 0) {
                    formats.splice(aqrar_idx, 1);
                    formats.splice(1, 0, "Sales Invoice Aqrar");
                }
            }
            print_format_cache[doctype] = formats;
            callback(formats);
        },
    });
}

function init_or_refresh_preview(frm) {
    if (!frm.doc.name) return;
    if (frm.in_form === false) return;

    var footer = frm.page.footer;
    footer.removeClass("hide");

    var existing = footer.find(".auto-print-preview");
    if (existing.length) {
        // Only reload iframe if preview is currently visible
        if (existing.find(".preview-body").is(":visible")) {
            refresh_iframe(frm, existing);
        }
        return;
    }

    get_print_formats(frm.doc.doctype, function (formats) {
        var panel = $(
            '<div class="auto-print-preview" style="margin: 0 15px 15px 15px; border: 1px solid #d1d8e0; border-radius: 8px; overflow: hidden; background: #fff;">' +
            '<div class="preview-header" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 15px; background: #f4f7fc; border-bottom: 1px solid #d1d8e0;">' +
            '<div style="display: flex; align-items: center; gap: 10px;">' +
            '<strong style="font-size: 13px;">' + __("Print Preview") + '</strong>' +
            '<select class="preview-format-select" style="font-size: 12px; padding: 2px 6px; border: 1px solid #d1d5db; border-radius: 4px; max-width: 200px;">' +
            formats.map(function (f) {
                return '<option value="' + f + '">' + f + '</option>';
            }).join("") +
            '</select>' +
            '</div>' +
            '<div style="display: flex; gap: 6px;">' +
            '<button class="btn btn-xs btn-default btn-toggle-preview">' + __("Show") + '</button>' +
            '<button class="btn btn-xs btn-default btn-close-preview">' + __("Close") + '</button>' +
            '</div>' +
            '</div>' +
            '<div class="preview-body">' +
            '<iframe class="preview-iframe" style="width: 100%; min-height: 600px; border: none; display: block;" src=""></iframe>' +
            '</div>' +
            '</div>'
        );

        footer.append(panel);

        // Start collapsed — body hidden, iframe not loaded yet
        panel.find(".preview-body").hide();
        panel.find(".preview-format-select").closest("div").hide();

        // Default to Sales Invoice Aqrar when available
        if (frm.doc.doctype === "Sales Invoice" && formats.indexOf("Sales Invoice Aqrar") !== -1) {
            panel.find(".preview-format-select").val("Sales Invoice Aqrar");
        }

        // Format selector change — reload iframe
        panel.find(".preview-format-select").on("change", function () {
            refresh_iframe(frm, panel);
        });

        // Toggle show/hide — load iframe on first show
        panel.find(".btn-toggle-preview").on("click", function () {
            var body = panel.find(".preview-body");
            var formatBar = panel.find(".preview-format-select").closest("div");
            var btn = $(this);
            if (body.is(":visible")) {
                body.hide();
                formatBar.hide();
                btn.text(__("Show"));
            } else {
                body.show();
                formatBar.show();
                btn.text(__("Hide"));
                refresh_iframe(frm, panel);
            }
        });
    });
}

function refresh_iframe(frm, panel) {
    var doctype = encodeURIComponent(frm.doc.doctype);
    var docname = encodeURIComponent(frm.doc.name);
    var format = encodeURIComponent(panel.find(".preview-format-select").val() || "Standard");
    var url = "/printview?doctype=" + doctype + "&name=" + docname + "&format=" + format + "&_ts=" + Date.now();

    var iframe = panel.find(".preview-iframe");
    iframe.attr("src", url);

    iframe.off("load").on("load", function () {
        try {
            var h = iframe[0].contentWindow.document.body.scrollHeight;
            if (h > 600) iframe.css("min-height", h + "px");
        } catch (e) {
            // cross-origin or empty — keep default height
        }
    });
}
