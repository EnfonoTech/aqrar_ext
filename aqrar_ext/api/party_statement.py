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
from frappe.utils import flt, formatdate, get_first_day, getdate, today

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


def get_ledger(party_type, party, company, from_date, to_date):
	"""Rows of the General Ledger for one party, split into opening / entries / closing."""
	from erpnext.accounts.report.general_ledger.general_ledger import execute

	filters = frappe._dict(
		company=company,
		from_date=from_date,
		to_date=to_date,
		party_type=party_type,
		party=[party],
		categorize_by="Categorize by Voucher (Consolidated)",
		show_remarks=1,
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
	frappe.has_permission("Company", "read", doc=company, throw=True)
	frappe.has_permission("GL Entry", "read", throw=True)

	if getdate(from_date) > getdate(to_date):
		frappe.throw(_("From Date cannot be after To Date"))


def build_context(party_type, party, company, from_date=None, to_date=None):
	# The General Ledger compares the two dates, so both must be the same type.
	from_date = str(getdate(from_date or get_first_day(today())))
	to_date = str(getdate(to_date or today()))
	validate_request(party_type, party, company, from_date, to_date)

	company_info = company_block(company)
	ledger = get_ledger(party_type, party, company, from_date, to_date)

	return frappe._dict(
		party_type=party_type,
		party_label_en=_("Supplier") if party_type == "Supplier" else _("Customer"),
		party_label_ar="المورد" if party_type == "Supplier" else "العميل",
		party=party_block(party_type, party),
		company=company_info,
		company_name=company,
		currency=company_info.currency,
		period=formatdate(from_date) + " — " + formatdate(to_date),
		generated_on=formatdate(today()),
		ledger=ledger,
		money=money,
		plain=plain,
		dr_cr=dr_cr,
		date=lambda value: formatdate(value) if value else "-",
	)


@frappe.whitelist()
def get_party_statement_html(party_type, party, company, from_date=None, to_date=None):
	"""The finished statement page, ready to print."""
	context = build_context(party_type, party, company, from_date, to_date)
	return {
		"html": frappe.render_template(TEMPLATE, context),
		"filename": "Statement_" + party_type + "_" + frappe.scrub(party),
	}


@frappe.whitelist()
def download_party_statement_pdf(party_type, party, company, from_date=None, to_date=None):
	"""The same page as a PDF download."""
	from frappe.utils.pdf import get_pdf

	context = build_context(party_type, party, company, from_date, to_date)
	html = frappe.render_template(TEMPLATE, context)

	frappe.local.response.filename = "Statement_" + party_type + "_" + frappe.scrub(party) + ".pdf"
	frappe.local.response.filecontent = get_pdf(html, {"orientation": "Portrait", "page-size": "A4"})
	frappe.local.response.type = "download"
