"""Party Statement: a bilingual ledger statement of one customer or supplier.

The statement used to exist only as a hand-made JS Print Format on the General
Ledger report. That format fetched the party, the company and their addresses with
synchronous browser requests and pulled a font from a public CDN, so it depended on
the browser session and an internet link, needed the right format chosen in the Print
dialog each time, and could not be used from the Customer or Supplier form.

Here the same layout is rendered on the server from the same General Ledger query
the report uses, so the page that prints is exactly the page that downloads, and one
click is enough from the General Ledger, the Customer form and the Supplier form.
"""

import html
import re

import frappe
from frappe import _
from frappe.core.doctype.user_permission.user_permission import get_permitted_documents
from frappe.utils import cstr, flt, formatdate, get_first_day, getdate, today

TEMPLATE = "aqrar_ext/templates/party_statement.html"
PARTY_TYPES = ("Customer", "Supplier")

# The company is printed under its trading name, not its ERPNext company name.
COMPANY_PRINT_NAMES = {
	"Seif Al Abour Trading Est": "Saif Al Abour Company For Trading",
}

ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

# Party master fields that hold the Arabic name, per party type.
ARABIC_NAME_FIELDS = {
	"Customer": "custom_customer_arabic_name",
	"Supplier": "custom_supplier_arabic_name",
}


def to_arabic_digits(value):
	return str(value or "").translate(ARABIC_DIGITS)


def is_saudi(country):
	country = (country or "").strip().lower()
	return "saudi" in country or country in ("ksa", "sa")


def money(value):
	return f"{abs(flt(value)):,.2f}"


def dr_cr(value):
	return "Dr" if flt(value) >= 0 else "Cr"


def plain(value):
	"""ERPNext stores remarks entity-escaped (&lt;); the template escapes once, so undo it first."""
	return html.unescape(str(value or "")).strip()


def strip_html(value):
	text = re.sub(r"<br\s*/?>", ", ", value or "", flags=re.I)
	text = re.sub(r"<[^>]+>", "", text)
	return re.sub(r"\s*,\s*(,\s*)+", ", ", text).strip()


def english_address(address):
	"""One line, in the order a Saudi address is read."""
	if not address:
		return ""
	parts = [address.get("address_line1")]
	if address.get("custom_building_number"):
		parts.append("Bldg " + str(address.get("custom_building_number")))
	parts += [address.get("custom_area"), address.get("city"), address.get("pincode")]
	country = address.get("country")
	if country:
		parts.append("Kingdom of Saudi Arabia" if is_saudi(country) else country)
	return ", ".join(p for p in parts if p)


def arabic_address(address):
	if not address:
		return ""
	parts = []
	if address.get("custom_address_line_1_arabic"):
		parts.append(to_arabic_digits(address.get("custom_address_line_1_arabic")))
	if address.get("custom_building_number"):
		parts.append("مبنى " + to_arabic_digits(address.get("custom_building_number")))
	if address.get("custom_area_arabic"):
		parts.append(to_arabic_digits(address.get("custom_area_arabic")))
	if address.get("custom_city_arabic"):
		parts.append(to_arabic_digits(address.get("custom_city_arabic")))
	if address.get("pincode"):
		parts.append(to_arabic_digits(address.get("pincode")))
	country = address.get("country")
	if country:
		parts.append(
			"المملكة العربية السعودية"
			if is_saudi(country)
			else to_arabic_digits(address.get("custom_country_arabic"))
		)
	return "، ".join(p for p in parts if p)


def has_content(address):
	return bool(
		address
		and (
			address.get("address_line1") or address.get("city") or address.get("custom_address_line_1_arabic")
		)
	)


def find_address(primary, link_doctype, link_name):
	"""The party's primary address, else its newest linked address that has content."""
	if primary:
		address = frappe.db.get_value("Address", primary, "*", as_dict=True)
		if has_content(address):
			return address

	if not link_name:
		return {}

	names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": link_doctype, "link_name": link_name},
		pluck="parent",
	)
	if not names:
		return {}

	candidates = frappe.get_all(
		"Address",
		filters={"name": ["in", names]},
		fields=["*"],
		order_by="is_primary_address desc, modified desc",
		limit_page_length=10,
	)
	for address in candidates:
		if has_content(address):
			return address
	return {}


def party_block(party_type, party):
	"""Name, Arabic name, ids and address of the customer or supplier."""
	doc = frappe.db.get_value(party_type, party, "*", as_dict=True) or {}
	name_field = "customer_name" if party_type == "Customer" else "supplier_name"
	primary = doc.get("customer_primary_address") or doc.get("supplier_primary_address")
	address = find_address(primary, party_type, party)

	return frappe._dict(
		name=doc.get(name_field) or party,
		name_ar=doc.get(ARABIC_NAME_FIELDS[party_type]) or "",
		vat=doc.get("tax_id") or doc.get("custom_vat_registration_number") or "",
		cr=doc.get("custom_cr_number") or "",
		address_en=english_address(address),
		address_ar=arabic_address(address),
		fallback_address=strip_html(doc.get("primary_address")),
	)


def company_block(company):
	doc = frappe.db.get_value("Company", company, "*", as_dict=True) or {}
	address = find_address(None, "Company", company)
	name = doc.get("company_name") or company

	return frappe._dict(
		name=COMPANY_PRINT_NAMES.get(company) or COMPANY_PRINT_NAMES.get(name) or name,
		name_ar=doc.get("custom_company_arabic") or "",
		vat=doc.get("tax_id") or doc.get("custom_vat_registration_number") or "",
		cr=doc.get("registration_details") or "",
		address_en=english_address(address),
		address_ar=arabic_address(address),
		fallback_address="",
		currency=doc.get("default_currency") or "",
	)


def letter_head_block(company):
	"""The company's own Letter Head (header and footer HTML) for the printed page.

	Company.default_letter_head first, else the site's default Letter Head -- the
	same choice ERPNext makes for its own print formats. Image letter heads are
	already stored as HTML in `content` / `footer`, so both kinds print the same.
	"""
	name = frappe.db.get_value("Company", company, "default_letter_head") or frappe.db.get_value(
		"Letter Head", {"is_default": 1, "disabled": 0}, "name"
	)
	if not name:
		return frappe._dict()

	letter_head = frappe.db.get_value(
		"Letter Head", {"name": name, "disabled": 0}, ["content", "footer"], as_dict=True
	)
	return letter_head or frappe._dict()


def get_ledger(party_type, party, company, from_date, to_date, dimensions=None):
	"""Rows of the General Ledger for one party, split into opening / entries / closing.

	`dimensions` ({"cost_center": [...], "project": [...], <accounting dimension>: [...]})
	narrows the ledger the way the General Ledger's own filters do, so a statement
	printed from a ledger filtered to one branch shows that branch only.
	"""
	from erpnext.accounts.report.general_ledger.general_ledger import execute

	filters = frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		party_type=party_type,
		party=[party],
		categorize_by="Categorize by Voucher (Consolidated)",
		show_remarks=1,
		**(dimensions or {}),
	)
	_columns, data = execute(filters)

	opening = closing = None
	entries = []
	for row in data or []:
		tag = " ".join(str(row.get(key) or "") for key in ("voucher_no", "account", "posting_date")).lower()
		if "closing" in tag:
			closing = row
		elif "opening" in tag:
			opening = row
		elif "total" in tag or row.get("is_total_row"):
			continue  # the report's own totals row; recomputed below
		elif row.get("voucher_no"):
			entries.append(row)

	typed = user_remarks(entries)
	for row in entries:
		row["user_remark"] = typed.get((row.get("voucher_type"), row.get("voucher_no")), "")

	total_debit = sum(flt(row.get("debit")) for row in entries)
	total_credit = sum(flt(row.get("credit")) for row in entries)
	opening_balance = flt(opening.get("debit")) - flt(opening.get("credit")) if opening else 0.0
	closing_balance = (
		flt(closing.get("debit")) - flt(closing.get("credit"))
		if closing
		else opening_balance + total_debit - total_credit
	)

	return frappe._dict(
		opening=opening,
		opening_balance=opening_balance,
		entries=entries,
		total_debit=total_debit,
		total_credit=total_credit,
		closing_balance=closing_balance,
	)


# Where each voucher type keeps the remark a user types, and what else decides it.
REMARK_SOURCES = {
	"Purchase Invoice": ["remarks", "bill_no"],
	"Sales Invoice": ["remarks", "po_no"],
	"Payment Entry": ["remarks", "custom_remarks"],
	"Journal Entry": ["user_remark"],
}


def is_auto_remark(voucher_type, doc):
	"""True when `doc.remarks` is the text ERPNext wrote because the user left it empty.

	Purchase Invoice: "Against Supplier Invoice <bill_no>[ dated <date>]" or "No Remarks".
	Sales Invoice: "Against Customer Order <po_no>[ dated <date>]" or "No Remarks".
	The date part is formatted with the date format of the day it was saved, so
	match on the prefix, not on a rebuilt string.
	"""
	text = plain(doc.get("remarks"))
	if not text:
		return False
	if text == plain(_("No Remarks")):
		return True
	ref_field, sentence = AUTO_REMARK_SENTENCE.get(voucher_type, (None, None))
	ref = plain(doc.get(ref_field)) if ref_field else ""
	# Only when the reference is the one on the document: "Against Supplier Invoice"
	# typed by hand about a different bill is a remark the user wrote.
	return bool(ref) and text.startswith(plain(_(sentence).replace("{0}", ref)))


# The sentence ERPNext writes into an empty `remarks`, and the field it quotes.
AUTO_REMARK_SENTENCE = {
	"Purchase Invoice": ("bill_no", "Against Supplier Invoice {0}"),
	"Sales Invoice": ("po_no", "Against Customer Order {0}"),
}


def user_remarks(entries):
	"""{(voucher_type, voucher_no): remark} with only the remarks a user typed.

	The General Ledger's own remarks column carries what ERPNext generates when the
	field is left empty ("No Remarks", "Against Supplier Invoice ...", "Amount SAR
	... received from ..."), which the client does not want on the statement.
	"""
	names = {}
	for row in entries:
		names.setdefault(row.get("voucher_type"), set()).add(row.get("voucher_no"))

	remarks = {}
	for voucher_type, voucher_nos in names.items():
		fields = REMARK_SOURCES.get(voucher_type)
		if not fields:
			continue
		for doc in frappe.get_all(
			voucher_type, filters={"name": ["in", list(voucher_nos)]}, fields=["name", *fields]
		):
			if voucher_type == "Journal Entry":
				text = doc.user_remark
			elif voucher_type == "Payment Entry":
				text = doc.remarks if doc.custom_remarks else ""
			else:
				text = "" if is_auto_remark(voucher_type, doc) else doc.remarks
			if plain(text):
				remarks[(voucher_type, doc.name)] = plain(text)
	return remarks


def validate_request(party_type, party, company, from_date, to_date):
	if party_type not in PARTY_TYPES:
		frappe.throw(_("Party Type must be Customer or Supplier"))
	if not party:
		frappe.throw(_("Select a Customer or Supplier to print a statement for"))
	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist").format(_(party_type), party))
	if not company:
		frappe.throw(_("Company is required"))

	# Public HTTP endpoint: never serve another party's ledger without a check. The
	# ledger is read straight from the General Ledger query, which has no permission
	# check of its own, so the ledger and the company are checked here too.
	frappe.has_permission(party_type, "read", doc=party, throw=True)
	frappe.has_permission("GL Entry", "read", throw=True)
	check_company_allowed(company)

	if getdate(from_date) > getdate(to_date):
		frappe.throw(_("From Date cannot be after To Date"))


def check_company_allowed(company):
	"""The user's own company restriction, not read access to the Company record.

	Branch staff often have no role that may open the Company record (jaleel on
	prod), so has_permission("Company", "read") refused them their own company's
	statement. What matters is the User Permission on Company: with one set, only
	those companies may be printed; without one, any company the ledger allows.
	"""
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))
	allowed = get_permitted_documents("Company")
	if allowed and company not in allowed:
		frappe.throw(_("You are not allowed to print statements for {0}").format(company), frappe.PermissionError)


def dimension_fieldnames():
	"""Ledger filters a statement may carry: cost center, project and the site's
	enabled accounting dimensions (Branch on Aqrar)."""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_accounting_dimensions,
	)

	names = ["cost_center", "project"]
	for dimension in get_accounting_dimensions(as_list=False):
		if not dimension.disabled and dimension.document_type != "Finance Book":
			names.append(dimension.fieldname)
	return names


def parse_dimensions(dimensions):
	"""{fieldname: [values]} with unknown keys and empty values dropped.

	Comes from the browser, so only known ledger fields pass: anything else would
	go straight into the General Ledger's filters."""
	if not dimensions:
		return {}
	if isinstance(dimensions, str):
		dimensions = frappe.parse_json(dimensions)
	allowed = dimension_fieldnames()
	clean = {}
	for fieldname, values in (dimensions or {}).items():
		if fieldname not in allowed or not values:
			continue
		values = [cstr(v) for v in (values if isinstance(values, (list, tuple)) else [values]) if cstr(v)]
		if values:
			clean[fieldname] = values
	return clean


def scope_label(dimensions):
	""""Warehouse Branch - SAT" for a branch statement, "" for the consolidated one."""
	return ", ".join(", ".join(values) for values in dimensions.values())


def build_context(party_type, party, company, from_date=None, to_date=None, dimensions=None):
	# The General Ledger compares the two dates, so both must be the same type.
	from_date = str(getdate(from_date or get_first_day(today())))
	to_date = str(getdate(to_date or today()))
	validate_request(party_type, party, company, from_date, to_date)
	dimensions = parse_dimensions(dimensions)

	company_info = company_block(company)
	ledger = get_ledger(party_type, party, company, from_date, to_date, dimensions)

	return frappe._dict(
		party_type=party_type,
		show_bill_no=party_type == "Supplier",
		party_label_en=_("Supplier") if party_type == "Supplier" else _("Customer"),
		party_label_ar="المورد" if party_type == "Supplier" else "العميل",
		party=party_block(party_type, party),
		company=company_info,
		letter_head=letter_head_block(company),
		# Footer name: the printed company name from the header, not the record ID.
		company_name=company_info.name,
		currency=company_info.currency,
		period=formatdate(from_date) + " — " + formatdate(to_date),
		scope=scope_label(dimensions),
		generated_on=formatdate(today()),
		ledger=ledger,
		money=money,
		plain=plain,
		dr_cr=dr_cr,
		date=lambda value: formatdate(value) if value else "-",
	)


def inline_site_images(html_text):
	"""Put the site's own public images (the letter head) into the page as data URIs.

	get_pdf() turns "/files/header.png" into "<site url>/files/header.png" and
	wkhtmltopdf then fetches it over HTTP. On prod the site URL is the site name,
	aqrar.enfonoerp.com, which resolves to the DEV box -- so every PDF waited on
	another server, and took over a minute whenever that box was slow. Reading the
	file from disk removes the network round trip altogether.
	"""
	import base64
	import mimetypes
	import os

	public = os.path.realpath(frappe.get_site_path("public", "files"))

	def replace(match):
		path = os.path.realpath(os.path.join(public, match.group(2)))
		mime = mimetypes.guess_type(path)[0] or ""
		if not path.startswith(public + os.sep) or not mime.startswith("image/") or not os.path.isfile(path):
			return match.group(0)
		with open(path, "rb") as fh:
			data = base64.b64encode(fh.read()).decode()
		return f"{match.group(1)}data:{mime};base64,{data}{match.group(3)}"

	return re.sub(r"""(src=["'])(?:https?://[^/"']+)?/files/([^"'?#]+)(["'])""", replace, html_text)


@frappe.whitelist()
def get_party_statement_html(party_type, party, company, from_date=None, to_date=None, dimensions=None):
	"""The finished statement page, ready to print."""
	context = build_context(party_type, party, company, from_date, to_date, dimensions)
	return {
		"html": frappe.render_template(TEMPLATE, context),
		"filename": "Statement_" + party_type + "_" + frappe.scrub(party),
	}


@frappe.whitelist()
def download_party_statement_pdf(party_type, party, company, from_date=None, to_date=None, dimensions=None):
	"""The same page as a PDF download."""
	from frappe.utils.pdf import get_pdf

	context = build_context(party_type, party, company, from_date, to_date, dimensions)
	html = inline_site_images(frappe.render_template(TEMPLATE, context))

	frappe.local.response.filename = "Statement_" + party_type + "_" + frappe.scrub(party) + ".pdf"
	frappe.local.response.filecontent = get_pdf(html, {"orientation": "Portrait", "page-size": "A4"})
	frappe.local.response.type = "download"
