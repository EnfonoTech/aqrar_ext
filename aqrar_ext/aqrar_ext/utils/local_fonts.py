"""Serve the Saudi Riyal symbol font from this app instead of a public CDN.

Ihjas 2026-10-29: "the PDF option is not working, not just invoice, quotation,
any document". Seventeen print formats on prod link the font's stylesheet from
cdn.jsdelivr.net. A browser fetches it in a second, but wkhtmltopdf's old WebKit
stalls on it for about two minutes (121 s with the link, 1 s without, same HTML,
on the prod box), so Download PDF ran into the web worker timeout.

The font (OFL-1.1, saudi-riyal-font 1.1.0) now ships in public/fonts/saudi_riyal
and the link is rewritten to it. A relative /assets URL is made absolute by
get_pdf and then served by the site's own nginx.
"""

import re

import frappe

LOCAL_CSS = "/assets/aqrar_ext/fonts/saudi_riyal/index.css"

# Any version, with or without the protocol: //cdn..., https://cdn..., @1.1.0/...
CDN_CSS = re.compile(
	r"(?:https?:)?//cdn\.jsdelivr\.net/npm/@emran-alhaddad/saudi-riyal-font(?:@[\w.\-]+)?/index\.css"
)

PRINT_FORMAT_FIELDS = ("html", "css")


def localise(text):
	"""`text` with every CDN link to the Riyal font pointed at the local copy."""
	if not text or "saudi-riyal-font" not in text:
		return text
	return CDN_CSS.sub(LOCAL_CSS, text)


def localise_print_format(doc, method=None):
	"""Print Format before_save: a format edited and saved with the CDN link keeps
	printing fast."""
	for field in PRINT_FORMAT_FIELDS:
		value = doc.get(field)
		fixed = localise(value)
		if fixed != value:
			doc.set(field, fixed)


def localise_all_print_formats():
	"""Rewrite the link in every saved print format. Returns the names changed."""
	changed = []
	for fmt in frappe.get_all(
		"Print Format",
		or_filters=[[field, "like", "%saudi-riyal-font%"] for field in PRINT_FORMAT_FIELDS],
		fields=["name", *PRINT_FORMAT_FIELDS],
	):
		values = {}
		for field in PRINT_FORMAT_FIELDS:
			fixed = localise(fmt.get(field))
			if fixed != fmt.get(field):
				values[field] = fixed
		if values:
			# Straight to the table: a print format may belong to a module this site
			# does not have in developer mode, and save() would try to export it.
			frappe.db.set_value("Print Format", fmt.name, values, update_modified=False)
			changed.append(fmt.name)
	if changed:
		frappe.clear_cache(doctype="Print Format")
	return changed
