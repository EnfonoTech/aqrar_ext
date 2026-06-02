# aqrar_ext: Get branch defaults for current user
import frappe


@frappe.whitelist()
def get_user_branch_defaults():
    """Return warehouse and cost_center from user's Branch Configuration."""
    user = frappe.session.user
    result = frappe.db.sql("""
        SELECT bcw.warehouse, bcc.cost_center
        FROM `tabBranch Configuration` bc
        INNER JOIN `tabBranch Configuration User` bcu ON bcu.parent = bc.name
        LEFT JOIN `tabBranch Configuration Warehouse` bcw ON bcw.parent = bc.name
        LEFT JOIN `tabBranch Configuration Cost Center` bcc ON bcc.parent = bc.name
        WHERE bcu.user = %s
        LIMIT 1
    """, user, as_dict=True)

    if result:
        return result[0]
    return {}
