"""Print format helper functions — exposed to Jinja via jenv hook."""
import frappe


def get_display_mode():
    """Return the current item display mode from Aqrar Settings."""
    mode = frappe.db.get_value(
        "Aqrar Settings", "Aqrar Settings", "item_display_mode"
    )
    return mode or "Item Name + Description"


def format_item_display(item_code, item_name, description):
    """Return HTML string for item display based on Aqrar Settings mode.

    Called from print format Jinja templates as: {{ format_item_display(...) }}
    """
    mode = get_display_mode()

    if mode == "Item Code":
        return "<b>{}</b>".format(frappe.utils.escape_html(item_code))

    if mode == "Item Name":
        return "<b>{}</b>".format(frappe.utils.escape_html(item_name))

    if mode == "Item Code + Description":
        out = "<b>{}</b>".format(frappe.utils.escape_html(item_code))
        if description and description != item_code:
            out += "<br>{}".format(frappe.utils.escape_html(description))
        return out

    # Default: Item Name + Description
    out = "<b>{}</b>".format(frappe.utils.escape_html(item_name))
    if description and description != item_name:
        out += "<br>{}".format(frappe.utils.escape_html(description))
    return out
