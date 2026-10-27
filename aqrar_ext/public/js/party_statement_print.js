// Party Statement: one click from the General Ledger, the Customer form and the
// Supplier form.
//
// The statement page is built on the server (aqrar_ext.api.party_statement), so
// printing it needs no Print dialog, no format to pick and no extra browser requests:
// the page is fetched once, loaded into a hidden frame and sent to the print dialog
// of the browser. Download PDF gives the same page as a file.

(function () {

const API = "aqrar_ext.api.party_statement";

function statement_args(values) {
    return {
        party_type: values.party_type,
        party: values.party,
        company: values.company,
        from_date: values.from_date,
        to_date: values.to_date,
    };
}

// Fetch the finished page and hand it to the browser's print dialog.
function print_statement(values) {
    frappe.show_alert({ message: __("Preparing statement…"), indicator: "blue" }, 4);

    return frappe
        .call({ method: API + ".get_party_statement_html", args: statement_args(values) })
        .then(function (r) {
            const html = r && r.message && r.message.html;
            if (!html) return;

            const frame = document.createElement("iframe");
            frame.setAttribute("aria-hidden", "true");
            frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
            document.body.appendChild(frame);

            const doc = frame.contentWindow.document;
            doc.open();
            doc.write(html);
            doc.close();

            // Let the frame lay the page out before the print dialog reads it.
            setTimeout(function () {
                try {
                    frame.contentWindow.focus();
                    frame.contentWindow.print();
                } catch (err) {
                    frappe.msgprint(__("Could not open the print dialog. Use Download PDF instead."));
                }
                setTimeout(function () { frame.remove(); }, 60000);
            }, 400);
        });
}

function download_statement(values) {
    const query = $.param(statement_args(values));
    window.open("/api/method/" + API + ".download_party_statement_pdf?" + query);
}

function valid_period(values) {
    if (values.from_date && values.to_date && values.from_date > values.to_date) {
        frappe.msgprint(__("From Date cannot be after To Date"));
        return false;
    }
    return true;
}

// Customer / Supplier form: ask for the company and period, then print.
function open_statement_dialog(party_type, party) {
    const dialog = new frappe.ui.Dialog({
        title: __("Print Statement") + " — " + party,
        size: "small",
        fields: [
            {
                fieldtype: "Link",
                fieldname: "company",
                label: __("Company"),
                options: "Company",
                reqd: 1,
                default: frappe.defaults.get_user_default("Company"),
            },
            { fieldtype: "Date", fieldname: "from_date", label: __("From Date"), reqd: 1, default: frappe.datetime.month_start() },
            { fieldtype: "Date", fieldname: "to_date", label: __("To Date"), reqd: 1, default: frappe.datetime.get_today() },
        ],
        primary_action_label: __("Print"),
        primary_action(values) {
            if (!valid_period(values)) return;
            dialog.hide();
            print_statement(Object.assign({ party_type: party_type, party: party }, values));
        },
        secondary_action_label: __("Download PDF"),
        secondary_action() {
            const values = dialog.get_values();
            if (!values || !valid_period(values)) return;
            dialog.hide();
            download_statement(Object.assign({ party_type: party_type, party: party }, values));
        },
    });
    dialog.show();
}

function add_form_button(frm, party_type) {
    if (frm.is_new()) return;
    frm.add_custom_button(
        __("Print Statement"),
        function () { open_statement_dialog(party_type, frm.doc.name); },
        __("View")
    );
}

frappe.ui.form.on("Customer", { refresh: function (frm) { add_form_button(frm, "Customer"); } });
frappe.ui.form.on("Supplier", { refresh: function (frm) { add_form_button(frm, "Supplier"); } });

// General Ledger report: print the statement for the party already chosen in the
// filters, no dialog.
function ledger_values(report) {
    const filters = report.get_filter_values ? report.get_filter_values() : {};
    let party = filters.party;
    if (Array.isArray(party)) {
        if (party.length > 1) {
            frappe.msgprint(__("Choose one Customer or Supplier in the Party filter to print a statement."));
            return null;
        }
        party = party[0];
    }

    if (!party || ["Customer", "Supplier"].indexOf(filters.party_type) === -1) {
        frappe.msgprint(__("Set Party Type to Customer or Supplier and choose the Party, then print the statement."));
        return null;
    }
    if (!filters.company || !filters.from_date || !filters.to_date) {
        frappe.msgprint(__("Company, From Date and To Date are required."));
        return null;
    }

    const values = {
        party_type: filters.party_type,
        party: party,
        company: filters.company,
        from_date: filters.from_date,
        to_date: filters.to_date,
    };
    return valid_period(values) ? values : null;
}

const LEDGER_PRINT = __("Print Statement");

function add_ledger_buttons() {
    const report = frappe.query_report;
    if (!report || report.report_name !== "General Ledger" || !report.page) return false;

    const toolbar = report.page.inner_toolbar;
    if (toolbar && toolbar.find('[data-label="' + encodeURIComponent(LEDGER_PRINT) + '"]').length) return true;

    report.page.add_inner_button(LEDGER_PRINT, function () {
        const values = ledger_values(report);
        if (values) print_statement(values);
    });
    return true;
}

function on_ledger() {
    const route = frappe.get_route();
    return route[0] === "query-report" && route[1] === "General Ledger";
}

// The report clears its own toolbar when it renders or refreshes, which on a large
// ledger happens AFTER the buttons were first added. So adding them once is not
// enough: while the General Ledger is open, put them back whenever they are missing.
let ledger_watcher = null;

function on_route_change() {
    if (!on_ledger()) {
        if (ledger_watcher) {
            clearInterval(ledger_watcher);
            ledger_watcher = null;
        }
        return;
    }
    if (ledger_watcher) return;

    add_ledger_buttons();
    ledger_watcher = setInterval(function () {
        if (!on_ledger()) {
            clearInterval(ledger_watcher);
            ledger_watcher = null;
            return;
        }
        add_ledger_buttons();
    }, 500);
}

$(document).on("page-change", on_route_change);
// First load straight onto the report.
$(function () { setTimeout(on_route_change, 500); });

})();
