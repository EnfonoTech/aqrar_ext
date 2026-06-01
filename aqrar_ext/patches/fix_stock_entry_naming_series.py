# Fix duplicate Stock Transfer naming by syncing naming series counter
import frappe
from datetime import date


def execute():
    current_year = date.today().year
    series_name = f"MAT-STE-{current_year}-"

    current = frappe.db.sql(
        "SELECT current FROM `tabSeries` WHERE name = %s",
        (series_name,)
    )
    current_val = current[0][0] if current else 0

    max_entry = frappe.db.sql(
        "SELECT name FROM `tabStock Entry` WHERE name LIKE %s ORDER BY name DESC LIMIT 1",
        (f"MAT-STE-{current_year}-%",)
    )

    if not max_entry:
        return

    actual_max = int(max_entry[0][0].split("-")[-1])

    if actual_max >= (current_val or 0):
        frappe.db.sql(
            "UPDATE `tabSeries` SET current = %s WHERE name = %s",
            (actual_max + 1, series_name)
        )
        frappe.db.commit()
