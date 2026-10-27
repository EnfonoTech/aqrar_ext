// Shared helpers for the item-entry scripts on selling / purchase documents.
//
// Entering one item used to fire seven server calls and nine field writes, and
// every write redrew the grid — on a slow link that is the blinking and the lag
// the front desk sees, and a fixed 700-800 ms timer decided whether the row's own
// price list or ERPNext's rate won. These helpers give the scripts two things:
//   * cached_call: one server call per distinct question, shared by every script
//     that asks it (the valuation column and the below-cost warning both ask for
//     the same floor).
//   * set_quiet: write a read-only display value into a row and repaint only that
//     cell, instead of frappe.model.set_value, which re-runs every handler and
//     redraws the table.
//
// Loaded first in app_include_js; the other files share its global scope.

frappe.provide("aqrar_ext.fd");

(function () {

const cache = {};

// Same key within ttl_ms -> the same promise, so concurrent callers share one request.
aqrar_ext.fd.cached_call = function (key, ttl_ms, make_request) {
    const hit = cache[key];
    if (hit && Date.now() - hit.at < ttl_ms) return hit.promise;

    const promise = Promise.resolve(make_request()).catch(function (err) {
        delete cache[key];
        throw err;
    });
    cache[key] = { at: Date.now(), promise: promise };
    return promise;
};

aqrar_ext.fd.forget = function (prefix) {
    Object.keys(cache).forEach(function (k) {
        if (k.indexOf(prefix) === 0) delete cache[k];
    });
};

// Display-only write: no change event, no form-dirty flag, one cell repainted.
// Returns true when the value actually changed.
aqrar_ext.fd.set_quiet = function (frm, cdt, cdn, fieldname, value) {
    const row = locals[cdt] && locals[cdt][cdn];
    if (!row || row[fieldname] === value) return false;

    row[fieldname] = value;
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
    if (grid_row) grid_row.refresh_field(fieldname);
    return true;
};

// Cost of one row, in company currency and the row's UOM. Shared by the valuation
// column and the below-cost warning.
aqrar_ext.fd.get_floor = function (frm, row) {
    const args = {
        item_code: row.item_code,
        warehouse: row.warehouse || row.s_warehouse || row.t_warehouse || frm.doc.set_warehouse || "",
        conversion_factor: row.conversion_factor || 1,
        qty: row.qty || 0,
        company: frm.doc.company || "",
    };
    return aqrar_ext.fd.cached_call("floor:" + JSON.stringify(args), 4000, function () {
        return frappe
            .call({ method: "aqrar_ext.aqrar_ext.utils.valuation_floor.get_valuation_floor", args: args })
            .then(function (r) {
                return flt(r && r.message && r.message.floor);
            });
    });
};

// Run fn(row) once ERPNext has finished filling the row for a newly chosen item.
//
// Our item_code handlers run BEFORE ERPNext's own, and its price lookup starts a
// little later still, so "no requests pending" says nothing yet. Wait for the
// get_item_details response that belongs to THIS row (matched by its row name),
// give ERPNext a moment to write it into the row, then let any follow-up requests
// drain. A fixed timer cannot do this: it loses the race on a slow link.
aqrar_ext.fd.when_item_ready = function (cdt, cdn, item_code, fn) {
    const ns = ".aqrar_ready_" + cdn;
    let done = false;

    const finish = function () {
        if (done) return;
        done = true;
        $(document).off("ajaxComplete" + ns);
        frappe.after_ajax(function () {
            const row = locals[cdt] && locals[cdt][cdn];
            if (!row || row.item_code !== item_code) return;
            fn(row);
        });
    };

    $(document).off("ajaxComplete" + ns).on("ajaxComplete" + ns, function (e, xhr, settings) {
        // The method is in the URL (/api/method/...get_item_details); the row name
        // is in the posted arguments.
        if (!settings || String(settings.url || "").indexOf("get_item_details") === -1) return;
        const sent = settings.data ? String(settings.data) : "";
        let decoded = sent;
        try { decoded = decodeURIComponent(sent); } catch (err) { /* keep raw */ }
        if (decoded.indexOf(cdn) === -1) return;
        setTimeout(finish, 120);
    });

    // An item whose details are never requested must not leave the hook dangling.
    setTimeout(finish, 5000);
};

})();
