frappe.provide("aqrar_ext.wf_shortcut");

aqrar_ext.wf_shortcut.update_count = function() {
    let $links = $('.shortcut-widget-box a, .widget.shortcut-widget-box .widget-title')
        .filter(function() {
            return $(this).text().trim().toLowerCase().includes("work flow approval")
                || $(this).text().trim().toLowerCase().includes("workflow approval");
        });
    if (!$links.length) return;

    frappe.call({
        method: "aqrar_ext.api.workflow.get_pending_approval_count",
        callback: function(r) {
            let count = r.message || 0;
            $('.shortcut-widget-box').each(function() {
                let $box = $(this);
                let txt = $box.find('.widget-title, a').first().text().trim().toLowerCase();
                if (!txt.includes("work flow approval") && !txt.includes("workflow approval")) return;
                $box.find('.wf-pending-count').remove();
                let $badge = $(`<span class="wf-pending-count" style="
                    display:inline-block;
                    margin-left:8px;
                    padding:2px 8px;
                    background:#f4f5f6;
                    color:${count > 0 ? '#e24c4c' : '#525252'};
                    border-radius:8px;
                    font-size:12px;
                    font-weight:500;
                    vertical-align:middle;
                ">${count}</span>`);
                let $target = $box.find('.widget-title').first();
                if (!$target.length) $target = $box.find('a').first();
                $target.append($badge);
            });
        }
    });
};

$(document).on("page-change app_ready", function() {
    setTimeout(aqrar_ext.wf_shortcut.update_count, 600);
    setTimeout(aqrar_ext.wf_shortcut.update_count, 1500);
});

frappe.after_ajax(function() {
    setTimeout(aqrar_ext.wf_shortcut.update_count, 1000);
});

setInterval(aqrar_ext.wf_shortcut.update_count, 60000);