"""Price Assist and item history endpoints.

Ported from fateh_trading (`ram` branch) so aqrar_ext owns the feature outright
and fateh_trading can be uninstalled. The SQL is kept close to the original on
purpose: the client rendering depends on these exact column names, and parity
with what was already running is worth more than a tidier shape.

Two things were changed on the way in:

* Every endpoint now checks read permission. In fateh_trading
  `get_item_warehouse_stock`, `get_item_insights` and `get_item_purchase_insights`
  were whitelisted with no check at all, so any logged-in user could read any
  customer's or supplier's rates for any item.
* Rates are read as `COALESCE(stock_uom_rate, rate)` where the caller wants a
  stock-UOM figure, matching the "all rate in stock uom" behaviour.

The weighted-discount feature was deliberately NOT ported.
"""

import frappe
from frappe.utils import cint, flt


def _check_read(doctype):
	frappe.has_permission(doctype, "read", throw=True)


def _base_rate(row):
	"""Rate per stock unit, but only when the row's UOM is not the stock UOM."""
	factor = flt(row.get("conversion_factor") or 0)
	if not factor or not row.get("stock_uom") or not row.get("uom"):
		return None
	if row["stock_uom"] == row["uom"]:
		return None
	return flt(row.get("rate") or 0) / factor


def _normalise(rows):
	for row in rows:
		row["rate"] = flt(row.get("rate") or 0)
		row["qty"] = flt(row.get("qty") or 0)
		row["stock_qty"] = flt(row.get("stock_qty") or 0)
		row["conversion_factor"] = flt(row.get("conversion_factor") or 0)
		row["base_rate"] = _base_rate(row)
	return rows


# --------------------------------------------------------------------------
# stock position
# --------------------------------------------------------------------------


@frappe.whitelist()
def get_item_warehouse_stock(item_code, company=None, limit=8):
	"""Available stock per warehouse for one item."""
	if not item_code:
		return []

	_check_read("Item")

	query = """
		SELECT
			b.warehouse,
			SUM(b.actual_qty) AS actual_qty,
			SUM(b.projected_qty) AS projected_qty
		FROM `tabBin` b
		INNER JOIN `tabWarehouse` w ON b.warehouse = w.name
		WHERE b.item_code = %s
	"""
	params = [item_code]

	if company:
		query += " AND w.company = %s"
		params.append(company)

	query += """
		GROUP BY b.warehouse
		ORDER BY SUM(b.actual_qty) DESC
		LIMIT %s
	"""
	params.append(cint(limit) or 8)

	data = frappe.db.sql(query, tuple(params), as_dict=True)

	for row in data:
		row["actual_qty"] = flt(row.get("actual_qty") or 0)
		row["projected_qty"] = flt(row.get("projected_qty") or 0)

	return data


def _valuation_rate(item_code, company=None):
	"""Weighted valuation rate from Bin, not the Item master."""
	query = """
		SELECT SUM(b.stock_value) / NULLIF(SUM(b.actual_qty), 0) AS valuation_rate
		FROM `tabBin` b
		WHERE b.item_code = %s AND b.actual_qty > 0
	"""
	params = [item_code]
	if company:
		query += (
			" AND EXISTS (SELECT 1 FROM `tabWarehouse` w"
			" WHERE w.name = b.warehouse AND w.company = %s)"
		)
		params.append(company)

	row = frappe.db.sql(query, tuple(params), as_dict=True)
	return flt(row[0].get("valuation_rate")) if row and row[0].get("valuation_rate") is not None else 0


# --------------------------------------------------------------------------
# Price Assist — sales
# --------------------------------------------------------------------------


@frappe.whitelist()
def get_item_insights(customer, item_code, company=None, limit=6, other_limit=5):
	"""This customer's price history, other customers' rates, stock and stats."""
	if not item_code:
		return {}

	_check_read("Sales Invoice")
	customer = customer or ""

	# customer_name as well as customer: the popup labels rows with it, and on a
	# site where Customer is named by series the id alone is unreadable.
	fields = """
		si.name AS si,
		si.posting_date,
		si.customer,
		cust.customer_name,
		sid.rate,
		sid.stock_uom_rate,
		sid.qty,
		sid.stock_qty,
		sid.uom,
		sid.stock_uom,
		sid.conversion_factor,
		si.currency
	"""

	price_history = _normalise(
		frappe.db.sql(
			f"""
			SELECT {fields}
			FROM `tabSales Invoice Item` sid
			INNER JOIN `tabSales Invoice` si ON sid.parent = si.name
			LEFT JOIN `tabCustomer` cust ON cust.name = si.customer
			WHERE sid.item_code = %s AND si.docstatus = 1 AND si.customer = %s
			ORDER BY si.posting_date DESC, si.name DESC
			LIMIT %s
			""",
			(item_code, customer, cint(limit) or 6),
			as_dict=True,
		)
	)

	other_customers = _normalise(
		frappe.db.sql(
			f"""
			SELECT {fields}
			FROM `tabSales Invoice Item` sid
			INNER JOIN `tabSales Invoice` si ON sid.parent = si.name
			LEFT JOIN `tabCustomer` cust ON cust.name = si.customer
			WHERE sid.item_code = %s AND si.docstatus = 1 AND si.customer != %s
			ORDER BY si.posting_date DESC, si.name DESC
			LIMIT %s
			""",
			(item_code, customer, cint(other_limit) or 5),
			as_dict=True,
		)
	)

	last_rate = flt(price_history[0]["rate"]) if price_history else 0
	row = frappe.db.sql(
		"""
		SELECT COALESCE(sii.stock_uom_rate, sii.rate) AS last_rate
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.item_code = %s AND si.customer = %s AND si.docstatus = 1
		ORDER BY si.posting_date DESC, si.name DESC
		LIMIT 1
		""",
		(item_code, customer),
		as_dict=True,
	)
	if row and row[0].get("last_rate") is not None:
		last_rate = flt(row[0]["last_rate"])

	return {
		"price_history": price_history,
		"other_customers": other_customers,
		"stock": get_item_warehouse_stock(item_code=item_code, company=company, limit=8),
		"last_purchase_rate": flt(frappe.db.get_value("Item", item_code, "last_purchase_rate")),
		"last_rate": last_rate,
		"valuation_rate": _valuation_rate(item_code, company),
	}


# --------------------------------------------------------------------------
# Price Assist — purchase
# --------------------------------------------------------------------------

_PURCHASE_SOURCES = (
	("Purchase Invoice", "Purchase Invoice Item", "pi", "pii"),
	("Purchase Receipt", "Purchase Receipt Item", "pr", "pri"),
)


def _purchase_rows(supplier, item_code, limit, same_supplier=True):
	"""Purchase history across both Purchase Invoice and Purchase Receipt."""
	operator = "=" if same_supplier else "!="
	rows = []

	for parent, child, p, c in _PURCHASE_SOURCES:
		rows.extend(
			frappe.db.sql(
				f"""
				SELECT
					{p}.name AS doc_name,
					{p}.name AS si,
					'{parent}' AS doctype,
					{p}.posting_date,
					{p}.supplier,
					sup.supplier_name,
					{c}.rate,
					{c}.stock_uom_rate,
					{c}.qty,
					{c}.stock_qty,
					{c}.uom,
					{c}.stock_uom,
					{c}.conversion_factor,
					{p}.currency
				FROM `tab{child}` {c}
				INNER JOIN `tab{parent}` {p} ON {p}.name = {c}.parent
				LEFT JOIN `tabSupplier` sup ON sup.name = {p}.supplier
				WHERE {c}.item_code = %s AND {p}.docstatus = 1
				  AND {p}.supplier {operator} %s
				ORDER BY {p}.posting_date DESC, {p}.name DESC
				LIMIT %s
				""",
				(item_code, supplier, limit),
				as_dict=True,
			)
		)

	rows.sort(key=lambda r: (r.get("posting_date") or "", r.get("doc_name") or ""), reverse=True)
	return _normalise(rows[:limit])


@frappe.whitelist()
def get_item_purchase_insights(supplier, item_code, company=None, limit=6, other_limit=5):
	"""This supplier's purchase history, other suppliers' rates, stock and stats."""
	if not item_code:
		return {}

	_check_read("Purchase Invoice")
	supplier = supplier or ""

	price_history = _purchase_rows(supplier, item_code, cint(limit) or 6, same_supplier=True)
	other_suppliers = _purchase_rows(
		supplier, item_code, cint(other_limit) or 5, same_supplier=False
	)
	# The popup renders this list with the sales field name.
	for row in other_suppliers:
		row["customer"] = row.get("supplier")
		row["customer_name"] = row.get("supplier_name")

	last_rate = 0
	if price_history:
		first = price_history[0]
		last_rate = flt(first.get("stock_uom_rate") or first.get("rate") or 0)

	return {
		"price_history": price_history,
		"other_customers": other_suppliers,
		"stock": get_item_warehouse_stock(item_code=item_code, company=company, limit=8),
		"last_purchase_rate": flt(frappe.db.get_value("Item", item_code, "last_purchase_rate")),
		"last_rate": last_rate,
		"valuation_rate": _valuation_rate(item_code, company),
	}


# --------------------------------------------------------------------------
# Show Price / Purchase History dialogs
# --------------------------------------------------------------------------


def _last_selling_rates(item_codes):
	"""item_code -> stock-UOM rate from that item's most recent Sales Invoice."""
	item_codes = list({code for code in (item_codes or []) if code})
	if not item_codes:
		return {}

	placeholders = ", ".join(["%s"] * len(item_codes))
	rows = frappe.db.sql(
		f"""
		SELECT item_code, last_selling_rate FROM (
			SELECT
				sii.item_code,
				COALESCE(sii.stock_uom_rate, sii.rate) AS last_selling_rate,
				ROW_NUMBER() OVER (
					PARTITION BY sii.item_code
					ORDER BY si.posting_date DESC, si.name DESC
				) AS rn
			FROM `tabSales Invoice Item` sii
			INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
			WHERE si.docstatus = 1 AND sii.item_code IN ({placeholders})
		) ranked WHERE rn = 1
		""",
		tuple(item_codes),
		as_dict=True,
	)
	return {row["item_code"]: row["last_selling_rate"] for row in rows}


@frappe.whitelist()
def get_item_sales_history(item_code=None, limit=20, cost_center=None):
	"""Recent sales rows for one item, for the Show Price History dialog.

	`cost_center` scopes the list to one branch. It is matched on the ITEM ROW's
	cost center, not the invoice header: the branch hook stamps both, and the row
	is what the money is actually booked against. Passing nothing returns every
	branch — a document with no cost center (Quotation has no such field at all)
	would otherwise get an empty dialog with no way to tell why.
	"""
	_check_read("Sales Invoice")

	params = {"limit": cint(limit) or 20}
	where = "si.docstatus = 1"
	if item_code:
		where += " AND sii.item_code = %(item_code)s"
		params["item_code"] = item_code
	if cost_center:
		where += " AND sii.cost_center = %(cost_center)s"
		params["cost_center"] = cost_center

	return frappe.db.sql(
		f"""
		SELECT
			si.posting_date,
			si.name           AS sales_invoice,
			si.customer,
			cust.customer_name,
			si.company,
			sii.item_code,
			sii.item_name,
			sii.cost_center,
			sii.qty,
			sii.stock_qty,
			sii.uom,
			sii.rate          AS sales_rate,
			sii.amount        AS sales_amount,
			si.currency,
			item.last_purchase_rate,
			sii.stock_uom_rate
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		LEFT JOIN `tabCustomer` cust ON cust.name = si.customer
		LEFT JOIN `tabItem` item ON item.name = sii.item_code
		WHERE {where}
		ORDER BY si.posting_date DESC, si.name DESC, sii.idx ASC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def get_item_purchase_history(item_code=None, limit=20, cost_center=None):
	"""Recent purchase rows for one item, across Purchase Invoice and Receipt.

	`cost_center` scopes the list to one branch, matched on the item row. See
	get_item_sales_history for why the row and not the header, and why an absent
	cost center means "all branches".
	"""
	_check_read("Purchase Invoice")

	limit = cint(limit) or 20
	params = {"limit": limit, "item_code": item_code, "cost_center": cost_center}

	blocks = []
	for parent, child, p, c in _PURCHASE_SOURCES:
		where = f"{p}.docstatus = 1"
		if item_code:
			where += f" AND {c}.item_code = %(item_code)s"
		if cost_center:
			where += f" AND {c}.cost_center = %(cost_center)s"
		blocks.append(
			f"""
			(SELECT
				{p}.posting_date,
				{p}.name AS doc_name,
				'{parent}' AS doctype,
				{p}.supplier,
				sup.supplier_name,
				{p}.company,
				{c}.item_code,
				{c}.item_name,
				{c}.cost_center,
				{c}.qty,
				{c}.stock_qty,
				{c}.rate AS purchase_rate,
				{c}.amount,
				{p}.currency,
				{c}.stock_uom_rate
			FROM `tab{child}` {c}
			JOIN `tab{parent}` {p} ON {p}.name = {c}.parent
			LEFT JOIN `tabSupplier` sup ON sup.name = {p}.supplier
			WHERE {where})
			"""
		)

	rows = frappe.db.sql(
		" UNION ALL ".join(blocks)
		+ " ORDER BY posting_date DESC, doc_name DESC LIMIT %(limit)s",
		params,
		as_dict=True,
	)

	last_selling = _last_selling_rates([row.get("item_code") for row in rows])
	for row in rows:
		row["last_selling_rate"] = last_selling.get(row.get("item_code")) or 0

	return rows
