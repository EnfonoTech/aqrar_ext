// CR-033: cross-doctype pending-approval queue with bulk workflow actions.

const AQRAR_WF_METHODS = "aqrar_ext.aqrar_ext.report.work_flow_approval.work_flow_approval";

frappe.query_reports["Work Flow Approval"] = {
    filters: [
        {
            fieldname: "user",
            label: __("Approver"),
            fieldtype: "Link",
            options: "User",
            default: frappe.session.user,
        },
        { fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
        {
            // NOTE: deliberately not named "doctype" — that key collides with
            // the report runner's own arguments.
            fieldname: "document_type",
            label: __("Document Type"),
            fieldtype: "Link",
            options: "DocType",
            get_query: function () {
                return { query: AQRAR_WF_METHODS + ".get_workflow_doctypes" };
            },
            on_change: function () {
                load_actions();
                frappe.query_report.refresh();
            },
        },
        { fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
        { fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
    ],

    after_datatable_render: function (dt) {
        $(dt.wrapper).find(".dt-cell--col-0").each(function (i) {
            if (i === 0) return;
            const $cell = $(this).css({ "text-align": "center", cursor: "pointer" });
            if (!$cell.find('input[type="checkbox"]').length) {
                $cell.html(
                    '<input type="checkbox" class="row-check" style="width:16px;height:16px;cursor:pointer;">'
                );
            }
            $cell.off("click.aqrar").on("click.aqrar", function (e) {
                if (!$(e.target).is("input")) {
                    const $box = $cell.find('input[type="checkbox"]');
                    $box.prop("checked", !$box.prop("checked"));
                }
            });
        });
    },

    onload: function (report) {
        report.page.add_inner_button(__("Apply Workflow Action"), function () {
            const docs = collect_selected_docs(report);
            if (!docs.length) {
                frappe.msgprint(__("Please select at least one document."));
                return;
            }

            const action = $("#wf-action-select").val();
            if (!action) {
                frappe.msgprint(__("Please select a Workflow Action."));
                return;
            }

            frappe.confirm(
                __("Apply {0} to {1} document(s)?", [frappe.utils.escape_html(action), docs.length]),
                function () {
                    frappe.call({
                        method: AQRAR_WF_METHODS + ".apply_bulk_workflow",
                        args: { docs: JSON.stringify(docs), action: action },
                        freeze: true,
                        freeze_message: __("Applying..."),
                        callback: function (r) {
                            if (r.exc) return;
                            frappe.msgprint({
                                title: __("Result"),
                                message: r.message,
                                indicator: "green",
                            });
                            frappe.query_report.refresh();
                        },
                    });
                }
            );
        });

        ensure_action_select(report);
    },
};

function ensure_action_select(report) {
    if (!report.page.page_form.length || $("#wf-action-select").length) {
        load_actions();
        return;
    }

    report.page.page_form.append(`
        <div style="display:inline-block;margin-left:8px;vertical-align:middle;">
            <select id="wf-action-select" style="height:30px;border:none;border-radius:25px;
                padding:0 14px;font-size:13px;font-family:inherit;color:#333;
                background-color:#f4f5f6;min-width:160px;cursor:pointer;outline:none;">
                <option value="">${__("Workflow Action")}</option>
            </select>
        </div>`);

    load_actions();
}

function collect_selected_docs(report) {
    const docs = [];
    $(report.datatable.wrapper)
        .find(".dt-row")
        .each(function (i) {
            if (!$(this).find("input.row-check").prop("checked")) return;
            const idx = parseInt($(this).attr("data-row-index"), 10);
            const row = report.data[isNaN(idx) ? i : idx];
            // Skip the report's own total/section rows, which carry no doctype.
            if (row && row.document_type && row.name) {
                docs.push({ doctype: row.document_type, name: row.name });
            }
        });
    return docs;
}

function load_actions() {
    const $select = $("#wf-action-select");
    if (!$select.length) return;

    const document_type = frappe.query_report.get_filter_value("document_type");
    const method = document_type
        ? AQRAR_WF_METHODS + ".get_workflow_actions"
        : AQRAR_WF_METHODS + ".get_all_workflow_actions";

    frappe.call({
        method: method,
        args: document_type ? { doctype: document_type } : {},
        callback: function (r) {
            $select.empty().append($("<option>").val("").text(__("Workflow Action")));
            (r.message || []).forEach(function (action) {
                $select.append($("<option>").val(action).text(action));
            });
        },
    });
}
