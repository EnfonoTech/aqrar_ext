import frappe


@frappe.whitelist()
def get_pending_approval_count():
    from aqrar_ext.aqrar_ext.report.work_flow_approval.work_flow_approval import (
        get_pending_approval_count as _get_count,
    )
    return _get_count()
