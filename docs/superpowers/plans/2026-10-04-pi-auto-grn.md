# PI → Auto Purchase Receipt (GRN) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Submitting a Purchase Invoice auto-creates and submits the Purchase Receipt that books its stock; the PI never updates stock itself.

**Architecture:** Three doc_events on Purchase Invoice in `aqrar_ext`: `before_validate` forces `update_stock = 0`; `on_submit` builds the PR with ERPNext's own `make_purchase_receipt` mapper (backdated per the date rule), submits it, and links the PI rows to it; `before_cancel` cancels the auto-created PRs (not `on_cancel`: Frappe's back-link check on the PI runs before `on_cancel`, and the auto PRs link to the PI). Return PIs get a return PR built with `make_return_doc`. Settings live in the `Aqrar Settings` Single; a marker Custom Field on Purchase Receipt ties each auto-PR to its PI.

**Tech Stack:** Frappe/ERPNext v15 (local bench: ERPNext 15.121.2 / Frappe 15.120.1), Python, `frappe.tests.utils.FrappeTestCase`.

**Spec:** `docs/superpowers/specs/2026-10-04-pi-auto-grn-design.md` — this plan **amends it in 3 places** (Task 0), found by reading ERPNext source:
1. PR is created in **`on_submit`, not `before_submit`**: ERPNext's `make_purchase_receipt` refuses a source PI that is not `docstatus = 1`. A stock-item PI row with no PR already books to *Stock Received But Not Billed* (ERPNext's supported "PI before PR" path), and the PR then clears it, so accounting nets to zero. Rows are linked to the PR afterwards.
2. `update_stock` is reset in **`before_validate`, not `validate`**: ERPNext's own `validate` runs `set_expense_account` using `update_stock`, so resetting afterwards would leave the stock-in-hand account on the PI rows.
3. A **return PI's rows already carry the original row's `purchase_receipt` / `pr_detail`** (copied by `make_return_doc`), so they cannot be filtered by "no pr_detail". Returns are only handled when the original PR is one we auto-created (carries the marker); otherwise skipped with a message.

---

## File structure

| File | Responsibility |
|---|---|
| `aqrar_ext/aqrar_ext/utils/auto_grn.py` (new) | all feature logic: settings read, date function, 3 hook functions |
| `aqrar_ext/aqrar_ext/utils/test_auto_grn.py` (new) | pure date tests + integration tests |
| `aqrar_ext/aqrar_ext/doctype/aqrar_settings/aqrar_settings.json` | 3 new settings fields |
| `aqrar_ext/setup_data.py` | marker Custom Field on Purchase Receipt |
| `aqrar_ext/hooks.py` | register the 3 hooks |
| `README.md` | feature row |

## Conventions to follow (checked in repo)
Tabs for indentation, ruff line length 110, `_()` on user text, `cint/flt/getdate` only, no raw SQL. Custom Fields via `setup_data.CUSTOM_FIELDS` (never fixtures). Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 0: Amend spec + throwaway test site

**Files:**
- Modify: `docs/superpowers/specs/2026-10-04-pi-auto-grn-design.md`

- [ ] **Step 1: Amend the spec.** In the "Components" table change the registration cell to:
  `doc_events["Purchase Invoice"]`: `before_validate` += `force_no_update_stock`; `on_submit` += `create_auto_grn`; `before_cancel` = `cancel_auto_grn`.
  Replace the whole "## Flow" section's first two paragraphs (`**validate**` and `**before_submit**` blocks) with:

```markdown
**before_validate** — if enabled and the PI has any stock item row: `doc.update_stock = 0`.
Must be before ERPNext's own validate, which derives each row's expense account from `update_stock`.

**on_submit** (runs after ERPNext's own on_submit, inside the same transaction) — skip if
disabled. Select rows: stock item and no `pr_detail`. No rows → return.
1. `make_purchase_receipt(PI.name, args={"filtered_children": [row names]})` — the stock mapper;
   it requires the PI to be docstatus 1, which it is by now.
2. Set `set_posting_time = 1`, `posting_date` per the date rule, `posting_time = 00:00:01`,
   marker field. `insert()` + `submit()` under the user's own permissions.
3. Link: write `purchase_receipt` / `pr_detail` onto the PI rows (`frappe.db.set_value` + in
   memory) and call `pi.update_billing_status_in_pr()` so the PR shows as billed.
Accounting: PI's own GL (posted first) debits Stock Received But Not Billed because the rows had
no PR yet; the PR then credits it and debits Stock In Hand. ERPNext supports this order.
Any exception rolls the whole PI submit back.
```
  Replace the "**Return PI**" paragraph's first sentence with: "Return PI rows already carry the original row's `purchase_receipt`/`pr_detail` (copied by ERPNext). Group the stock rows by that original PR; only when the original PR carries our marker, build a return PR with `make_return_doc("Purchase Receipt", pr)` limited to those rows and the returned qty. Otherwise skip with a message."

- [ ] **Step 2: Create the throwaway site** (never use a client site). Needs the local MariaDB root password.

```bash
cd ~/Developer/frappe-bench
bench get-app --soft-link "/Users/sayanthns/Documents/Claude Code Main/Production/AQRAR/aqrar_ext"
bench new-site aqrar-test.local --admin-password admin --db-root-password <MARIADB_ROOT_PASSWORD> --install-app erpnext
bench --site aqrar-test.local install-app aqrar_ext
bench --site aqrar-test.local set-config allow_tests true
bench --site aqrar-test.local set-config developer_mode 1
```
Expected: site created, both apps installed. If `--soft-link` is unsupported, run `ln -s "<repo>" apps/aqrar_ext` then `./env/bin/pip install -e apps/aqrar_ext` and append `aqrar_ext` to `sites/apps.txt`.

- [ ] **Step 3: Confirm the test runner works** (also creates `_Test Company` records):

```bash
cd ~/Developer/frappe-bench
bench --site aqrar-test.local run-tests --app aqrar_ext --module aqrar_ext.aqrar_ext.doctype.branch_configuration.test_branch_configuration
```
Expected: runs without import/DB errors (pass or "0 tests" is fine; a crash is not).

- [ ] **Step 4: Commit**

```bash
cd "/Users/sayanthns/Documents/Claude Code Main/Production/AQRAR/aqrar_ext"
git add docs && git commit -m "docs: amend auto-GRN spec after reading ERPNext source

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Settings fields

**Files:**
- Modify: `aqrar_ext/aqrar_ext/doctype/aqrar_settings/aqrar_settings.json`

- [ ] **Step 1: Edit `field_order` and `fields`.** Replace `"field_order": ["item_display_mode"]` with:

```json
 "field_order": [
  "item_display_mode",
  "auto_grn_section",
  "auto_grn_enabled",
  "auto_grn_system_start_date",
  "auto_grn_backdate_days"
 ],
```
  and append these objects to `fields` (after `item_display_mode`):

```json
  {
   "fieldname": "auto_grn_section",
   "fieldtype": "Section Break",
   "label": "Purchase Invoice Auto GRN"
  },
  {
   "default": "0",
   "description": "On Purchase Invoice submit, create and submit the Purchase Receipt automatically. The invoice then never updates stock itself.",
   "fieldname": "auto_grn_enabled",
   "fieldtype": "Check",
   "label": "Auto-create GRN on Purchase Invoice Submit"
  },
  {
   "default": "2026-09-01",
   "description": "Until the system is Backdate Days old, every auto GRN is dated this day.",
   "fieldname": "auto_grn_system_start_date",
   "fieldtype": "Date",
   "label": "System Start Date"
  },
  {
   "default": "90",
   "description": "After that, the auto GRN is dated this many days before the Purchase Invoice posting date.",
   "fieldname": "auto_grn_backdate_days",
   "fieldtype": "Int",
   "label": "GRN Backdate Days"
  }
```
  Also bump `"modified"` to `"2026-10-04 00:00:00.000000"`.

- [ ] **Step 2: Migrate and verify**

```bash
cd ~/Developer/frappe-bench
bench --site aqrar-test.local migrate
bench --site aqrar-test.local execute frappe.db.get_single_value --args '["Aqrar Settings", "auto_grn_backdate_days"]'
```
Expected: migrate OK; the second command prints `90` (or `None` — acceptable, code falls back to constants).

- [ ] **Step 3: Commit**

```bash
cd "/Users/sayanthns/Documents/Claude Code Main/Production/AQRAR/aqrar_ext"
git add aqrar_ext/aqrar_ext/doctype/aqrar_settings && git commit -m "feat: auto-GRN settings on Aqrar Settings

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Date rule (pure function, TDD)

**Files:**
- Create: `aqrar_ext/aqrar_ext/utils/auto_grn.py`
- Create: `aqrar_ext/aqrar_ext/utils/test_auto_grn.py`

- [ ] **Step 1: Write the failing test** — `test_auto_grn.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from aqrar_ext.aqrar_ext.utils.auto_grn import get_grn_posting_date

START = "2026-09-01"


class TestGrnPostingDate(FrappeTestCase):
	def test_before_cutoff_uses_start_date(self):
		# cutoff = 2026-09-01 + 90 days = 2026-11-30
		result = get_grn_posting_date("2026-10-15", "2026-11-29", START, 90)
		self.assertEqual(result, getdate("2026-09-01"))

	def test_on_cutoff_uses_pi_date_minus_days(self):
		result = get_grn_posting_date("2026-12-10", "2026-11-30", START, 90)
		self.assertEqual(result, getdate("2026-09-11"))

	def test_after_cutoff_ignores_start_date(self):
		result = get_grn_posting_date("2027-01-10", "2027-02-01", START, 90)
		self.assertEqual(result, getdate("2026-10-12"))

	def test_after_cutoff_literal_rule_even_before_start(self):
		# Rule A is applied literally: a PI dated well before the cutoff entered
		# after it gets PI date - 90, which can precede the system start date.
		result = get_grn_posting_date("2026-10-15", "2026-12-15", START, 90)
		self.assertEqual(result, getdate("2026-07-17"))

	def test_backdate_days_is_configurable(self):
		# cutoff = 2026-09-01 + 10 = 2026-09-11
		self.assertEqual(
			get_grn_posting_date("2026-09-20", "2026-09-10", START, 10), getdate("2026-09-01")
		)
		self.assertEqual(
			get_grn_posting_date("2026-09-20", "2026-09-11", START, 10), getdate("2026-09-10")
		)
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'get_grn_posting_date'`):

```bash
cd ~/Developer/frappe-bench
bench --site aqrar-test.local run-tests --app aqrar_ext --module aqrar_ext.aqrar_ext.utils.test_auto_grn
```

- [ ] **Step 3: Implement** — `auto_grn.py`:

```python
"""Purchase Invoice -> automatic Purchase Receipt (GRN).

On submit of a Purchase Invoice the stock is booked by a Purchase Receipt created
here, never by the invoice itself (``update_stock`` is forced off). The receipt is
backdated: a fixed system start date until the system is ``backdate_days`` old,
then ``backdate_days`` before the invoice's posting date.

Hooks (registered in hooks.py under doc_events["Purchase Invoice"]):
  before_validate -> force_no_update_stock
  on_submit       -> create_auto_grn
  before_cancel   -> cancel_auto_grn
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

MARKER_FIELD = "custom_auto_grn_invoice"
GRN_POSTING_TIME = "00:00:01"

# Used when Aqrar Settings has no stored value yet (a Single's defaults are not
# materialised until it is first saved).
DEFAULT_START_DATE = "2026-09-01"
DEFAULT_BACKDATE_DAYS = 90


def get_grn_posting_date(pi_posting_date, today_date, start_date, backdate_days):
	"""Posting date for the auto GRN.

	today <  start + backdate_days -> start_date
	today >= start + backdate_days -> pi_posting_date - backdate_days
	"""
	start = getdate(start_date)
	days = cint(backdate_days)
	if getdate(today_date) < getdate(add_days(start, days)):
		return start
	return getdate(add_days(getdate(pi_posting_date), -days))
```

- [ ] **Step 4: Run, expect PASS** (same command; 5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add aqrar_ext/aqrar_ext/utils/auto_grn.py aqrar_ext/aqrar_ext/utils/test_auto_grn.py
git commit -m "feat: auto-GRN posting date rule

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Marker Custom Field + settings reader

**Files:**
- Modify: `aqrar_ext/setup_data.py` (insert directly above the line `for _dt in _RETURN_QTY_DOCTYPES:` near line 497)
- Modify: `aqrar_ext/aqrar_ext/utils/auto_grn.py`

- [ ] **Step 1: Add the Custom Field** in `setup_data.py`:

```python
# Purchase Receipt: the Purchase Invoice that auto-created it
# (utils/auto_grn.py). Read-only: it is system bookkeeping, and cancel cascades
# key on it.
CUSTOM_FIELDS.setdefault("Purchase Receipt", []).append(
	{
		"fieldname": "custom_auto_grn_invoice",
		"label": "Auto GRN From Invoice",
		"fieldtype": "Link",
		"options": "Purchase Invoice",
		"insert_after": "supplier_delivery_note",
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"search_index": 1,
	}
)
```

- [ ] **Step 2: Add the settings reader** to `auto_grn.py` (below the date function):

```python
def is_enabled():
	return cint(frappe.db.get_single_value("Aqrar Settings", "auto_grn_enabled"))


def get_grn_date_for(pi):
	start = frappe.db.get_single_value("Aqrar Settings", "auto_grn_system_start_date")
	days = frappe.db.get_single_value("Aqrar Settings", "auto_grn_backdate_days")
	return get_grn_posting_date(
		pi.posting_date,
		today(),
		start or DEFAULT_START_DATE,
		DEFAULT_BACKDATE_DAYS if days is None else days,
	)
```

- [ ] **Step 3: Migrate and verify the field exists**

```bash
cd ~/Developer/frappe-bench
bench --site aqrar-test.local migrate
bench --site aqrar-test.local execute frappe.db.exists --args '["Custom Field", "Purchase Receipt-custom_auto_grn_invoice"]'
```
Expected: prints `Purchase Receipt-custom_auto_grn_invoice`.

- [ ] **Step 4: Commit**

```bash
git add aqrar_ext/setup_data.py aqrar_ext/aqrar_ext/utils/auto_grn.py
git commit -m "feat: auto-GRN marker field and settings reader

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Force `update_stock = 0`

**Files:**
- Modify: `aqrar_ext/aqrar_ext/utils/auto_grn.py`, `aqrar_ext/aqrar_ext/utils/test_auto_grn.py`, `aqrar_ext/hooks.py`

- [ ] **Step 1: Add shared test setup + failing tests** to `test_auto_grn.py` (add imports at top; append class):

```python
import erpnext
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

COMPANY = "_Test Company"
STOCK_ITEM = "_Test Item"
NON_STOCK_ITEM = "_Test Non Stock Item"
WAREHOUSE = "_Test Warehouse - _TC"


class AutoGrnTestCase(FrappeTestCase):
	"""Shared setup: perpetual inventory on, feature on, rule dates fixed."""

	def setUp(self):
		erpnext.set_perpetual_inventory(1, COMPANY)
		self.set_rule(enabled=1, start="2026-09-01", days=90)

	def tearDown(self):
		erpnext.set_perpetual_inventory(0, COMPANY)

	@staticmethod
	def set_rule(enabled=1, start="2026-09-01", days=90):
		frappe.db.set_single_value(
			"Aqrar Settings",
			{
				"auto_grn_enabled": enabled,
				"auto_grn_system_start_date": start,
				"auto_grn_backdate_days": days,
			},
		)

	@staticmethod
	def make_pi(**kwargs):
		kwargs.setdefault("company", COMPANY)
		kwargs.setdefault("warehouse", WAREHOUSE)
		kwargs.setdefault("item_code", STOCK_ITEM)
		kwargs.setdefault("qty", 5)
		kwargs.setdefault("rate", 50)
		return make_purchase_invoice(**kwargs)


class TestForceNoUpdateStock(AutoGrnTestCase):
	def test_update_stock_is_reset_for_stock_items(self):
		pi = self.make_pi(update_stock=1, do_not_submit=True)
		self.assertEqual(pi.update_stock, 0)

	def test_update_stock_untouched_when_disabled(self):
		self.set_rule(enabled=0)
		pi = self.make_pi(update_stock=1, do_not_submit=True)
		self.assertEqual(pi.update_stock, 1)

	def test_update_stock_untouched_without_stock_items(self):
		pi = self.make_pi(update_stock=1, item_code=NON_STOCK_ITEM, do_not_submit=True)
		self.assertEqual(pi.update_stock, 1)
```

- [ ] **Step 2: Run, expect FAIL** (first test: `update_stock` stays 1). Same run-tests command as Task 2.

- [ ] **Step 3: Implement** — append to `auto_grn.py`:

```python
def force_no_update_stock(doc, method=None):
	"""A PI with stock items must not move stock itself; the auto GRN does.

	before_validate, not validate: ERPNext's validate derives each row's expense
	account from ``update_stock`` (Stock In Hand vs Stock Received But Not Billed),
	so it must already be off when that runs.
	"""
	if not is_enabled() or not cint(doc.get("update_stock")):
		return
	if doc.get_stock_items():
		doc.update_stock = 0
```

- [ ] **Step 4: Register in `hooks.py`.** After the `_STANDARD_SELLING_HOOK` constant add:

```python
# Purchase Invoice -> auto Purchase Receipt (GRN): the invoice never moves stock,
# the receipt created on submit does. See utils/auto_grn.py.
_AUTO_GRN_NO_UPDATE_STOCK_HOOK = "aqrar_ext.aqrar_ext.utils.auto_grn.force_no_update_stock"
_AUTO_GRN_CREATE_HOOK = "aqrar_ext.aqrar_ext.utils.auto_grn.create_auto_grn"
_AUTO_GRN_CANCEL_HOOK = "aqrar_ext.aqrar_ext.utils.auto_grn.cancel_auto_grn"
```
  and change the Purchase Invoice `before_validate` entry to `[_AUTO_GRN_NO_UPDATE_STOCK_HOOK, _RETURN_QTY_HOOK, _RETURN_UOM_HOOK]`.

- [ ] **Step 5: Run, expect PASS.** Then commit:

```bash
git add aqrar_ext/hooks.py aqrar_ext/aqrar_ext/utils
git commit -m "feat: force update_stock off on Purchase Invoice when auto-GRN is on

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Create the PR on submit

**Files:**
- Modify: `aqrar_ext/aqrar_ext/utils/auto_grn.py`, `aqrar_ext/aqrar_ext/utils/test_auto_grn.py`, `aqrar_ext/hooks.py`

- [ ] **Step 1: Failing tests** — append to `test_auto_grn.py`:

```python
def linked_receipts(pi_name):
	return frappe.get_all(
		"Purchase Receipt",
		filters={MARKER: pi_name, "docstatus": 1},
		fields=["name", "posting_date", "supplier"],
	)


MARKER = "custom_auto_grn_invoice"


class TestCreateAutoGrn(AutoGrnTestCase):
	def test_submit_creates_one_submitted_receipt(self):
		pi = self.make_pi(posting_date="2026-10-15", qty=5, rate=50)
		prs = linked_receipts(pi.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.docstatus, 1)
		self.assertEqual(pr.items[0].warehouse, WAREHOUSE)
		self.assertEqual(pr.items[0].qty, 5)
		self.assertEqual(pr.items[0].rate, 50)

	def test_receipt_dated_start_date_before_cutoff(self):
		# `today` is the real date (>= 2026-10-04); pin the rule so cutoff is in the future
		self.set_rule(start=frappe.utils.today(), days=90)
		pi = self.make_pi(posting_date=frappe.utils.today())
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(getdate(pr.posting_date), getdate(frappe.utils.today()))

	def test_receipt_dated_pi_minus_days_after_cutoff(self):
		# start long ago => cutoff passed => PI date - 90
		self.set_rule(start="2020-01-01", days=90)
		pi = self.make_pi(posting_date="2026-10-15")
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(getdate(pr.posting_date), getdate("2026-07-17"))

	def test_pi_rows_linked_and_receipt_fully_billed(self):
		pi = self.make_pi()
		pr_name = linked_receipts(pi.name)[0].name
		pi.reload()
		pr = frappe.get_doc("Purchase Receipt", pr_name)
		self.assertEqual(pi.items[0].purchase_receipt, pr_name)
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertEqual(pr.per_billed, 100)

	def test_stock_actually_received(self):
		pi = self.make_pi(qty=7)
		bin_qty = frappe.db.sql(
			"""select sum(actual_qty) from `tabStock Ledger Entry`
			where voucher_type='Purchase Receipt' and item_code=%s and warehouse=%s
			and voucher_no in (select name from `tabPurchase Receipt` where custom_auto_grn_invoice=%s)""",
			(STOCK_ITEM, WAREHOUSE, pi.name),
		)[0][0]
		self.assertEqual(bin_qty, 7)

	def test_purchase_invoice_posts_no_stock_ledger_entries(self):
		pi = self.make_pi()
		self.assertFalse(
			frappe.db.exists("Stock Ledger Entry", {"voucher_type": "Purchase Invoice", "voucher_no": pi.name})
		)

	def test_stock_received_but_not_billed_nets_to_zero(self):
		pi = self.make_pi(qty=5, rate=50)
		pr_name = linked_receipts(pi.name)[0].name
		account = frappe.get_cached_value("Company", COMPANY, "stock_received_but_not_billed")
		net = frappe.db.sql(
			"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
			where is_cancelled = 0 and account = %s and voucher_no in (%s, %s)""",
			(account, pi.name, pr_name),
		)[0][0]
		self.assertEqual(net, 0)

	def test_non_stock_only_invoice_creates_no_receipt(self):
		pi = self.make_pi(item_code=NON_STOCK_ITEM)
		self.assertEqual(linked_receipts(pi.name), [])

	def test_row_with_existing_receipt_link_is_skipped(self):
		first = self.make_pi()
		pr_name = linked_receipts(first.name)[0].name
		# A second invoice row already linked to a receipt must not get another one.
		pi = self.make_pi(do_not_submit=True)
		pr_item = frappe.get_doc("Purchase Receipt", pr_name).items[0].name
		pi.items[0].purchase_receipt = pr_name
		pi.items[0].pr_detail = pr_item
		pi.items[0].qty = 5
		pi.save()
		pi.submit()
		self.assertEqual(linked_receipts(pi.name), [])

	def test_disabled_creates_nothing(self):
		self.set_rule(enabled=0)
		pi = self.make_pi(update_stock=1)
		self.assertEqual(linked_receipts(pi.name), [])

	def test_failure_rolls_back_invoice_submit(self):
		self.set_rule(start="2020-01-01", days=90)
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "2026-12-31")
		try:
			pi = self.make_pi(posting_date="2026-10-15", do_not_submit=True)
			with self.assertRaises(frappe.ValidationError):
				pi.submit()
		finally:
			frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", None)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 0)
```

- [ ] **Step 2: Run, expect FAIL** (no receipts created; `AttributeError`/`IndexError` on `linked_receipts(...)[0]`).

- [ ] **Step 3: Implement** — append to `auto_grn.py`:

```python
def create_auto_grn(doc, method=None):
	"""on_submit: book the PI's stock through a Purchase Receipt (or return PR)."""
	if not is_enabled():
		return
	if cint(doc.get("is_return")):
		_create_return_grn(doc)
	else:
		_create_forward_grn(doc)


def _stamp(pr, pi):
	"""Backdate the receipt, tag it with its source invoice."""
	pr.set_posting_time = 1
	pr.posting_date = get_grn_date_for(pi)
	pr.posting_time = GRN_POSTING_TIME
	pr.set(MARKER_FIELD, pi.name)
	pr.remarks = _("Auto-created from Purchase Invoice {0}").format(pi.name)


def _create_forward_grn(pi):
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt

	stock_items = set(pi.get_stock_items())
	rows = [r for r in pi.items if r.item_code in stock_items and not r.pr_detail]
	if not rows:
		return

	# make_purchase_receipt treats an empty filter as "every row", so never call it
	# with none (guarded above).
	pr = make_purchase_receipt(pi.name, args={"filtered_children": [r.name for r in rows]})
	if not pr.get("items"):
		return

	_stamp(pr, pi)
	pr.insert()
	pr.submit()
	_link_rows(pi, pr)


def _link_rows(pi, pr):
	"""Point the PI rows at the receipt and refresh the receipt's billing status.

	Done after submit because the mapper needs a submitted PI. The PI's GL was
	already posted against Stock Received But Not Billed, which is the account the
	receipt credits, so the link changes bookkeeping, not ledger balances.
	"""
	by_pi_row = {item.purchase_invoice_item: item for item in pr.items}
	for row in pi.items:
		pr_item = by_pi_row.get(row.name)
		if not pr_item:
			continue
		values = {"purchase_receipt": pr.name, "pr_detail": pr_item.name}
		frappe.db.set_value("Purchase Invoice Item", row.name, values, update_modified=False)
		row.update(values)

	pi.update_billing_status_in_pr(update_modified=False)


def _create_return_grn(pi):
	pass  # Task 6
```

- [ ] **Step 4: Register on_submit in `hooks.py`.** Purchase Invoice `on_submit` becomes `[_LAST_PURCHASE_PRICE_HOOK, _STANDARD_SELLING_HOOK, _AUTO_GRN_CREATE_HOOK]`.

- [ ] **Step 5: Run, expect PASS.** If a test fails, read it as a finding and do not weaken the test — likely suspects:
  - `test_pi_rows_linked…` fails with a stale-document error → `_link_rows` needs `pi.reload()` ordering revisited.
  - `…nets_to_zero` ≠ 0 → check the PR/PI rates differ (mapper recalculated) and report; accounting must reconcile.
  - `…rolls_back…` doesn't raise → `stock_frozen_upto` semantics: confirm the frozen date check applies to backdated PR.

- [ ] **Step 6: Commit**

```bash
git add aqrar_ext/hooks.py aqrar_ext/aqrar_ext/utils
git commit -m "feat: create and submit Purchase Receipt when a Purchase Invoice is submitted

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Return invoices

**Files:**
- Modify: `aqrar_ext/aqrar_ext/utils/auto_grn.py` (replace the `_create_return_grn` stub), `aqrar_ext/aqrar_ext/utils/test_auto_grn.py`

- [ ] **Step 1: Failing tests** — append:

```python
class TestReturnGrn(AutoGrnTestCase):
	def make_return(self, original, qty):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		ret = make_return_doc("Purchase Invoice", original.name)
		ret.items[0].qty = -qty
		ret.items[0].received_qty = -qty
		ret.items[0].stock_qty = -qty
		ret.insert()
		ret.submit()
		return ret

	def test_return_pi_creates_return_receipt(self):
		original = self.make_pi(qty=10)
		original_pr = linked_receipts(original.name)[0].name
		ret = self.make_return(original, qty=3)
		prs = linked_receipts(ret.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.is_return, 1)
		self.assertEqual(pr.return_against, original_pr)
		self.assertEqual(pr.items[0].qty, -3)

	def test_return_pi_without_auto_grn_original_is_skipped(self):
		self.set_rule(enabled=0)
		original = self.make_pi(update_stock=1, qty=10)
		self.set_rule(enabled=1)
		ret = self.make_return(original, qty=3)
		self.assertEqual(linked_receipts(ret.name), [])
		self.assertEqual(ret.docstatus, 1)

	def test_return_cancel_cascades(self):
		original = self.make_pi(qty=10)
		ret = self.make_return(original, qty=3)
		pr_name = linked_receipts(ret.name)[0].name
		ret.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)
```

- [ ] **Step 2: Run, expect FAIL** (`_create_return_grn` is a stub; first test `IndexError`).

- [ ] **Step 3: Implement** — replace the stub:

```python
def _create_return_grn(pi):
	"""Return PR for a return PI.

	ERPNext copies the original row's purchase_receipt / pr_detail onto each return
	row, so rows are grouped by the original receipt. Only receipts we created
	(carrying MARKER_FIELD) are returned automatically: a receipt entered by hand
	may already have its own return, and a second one would double the stock-out.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	if not pi.get("return_against"):
		return
	if frappe.db.exists("Purchase Receipt", {MARKER_FIELD: pi.name, "docstatus": 1}):
		return

	stock_items = set(pi.get_stock_items())
	wanted = {}
	skipped = False
	for row in pi.items:
		if row.item_code not in stock_items:
			continue
		if row.purchase_receipt and row.pr_detail and frappe.db.get_value(
			"Purchase Receipt", row.purchase_receipt, MARKER_FIELD
		):
			wanted.setdefault(row.purchase_receipt, {})[row.pr_detail] = row
		else:
			skipped = True

	if skipped:
		frappe.msgprint(
			_(
				"Some stock rows were not returned automatically because their original "
				"Purchase Receipt was not created by Auto GRN. Return that stock manually."
			),
			indicator="orange",
			alert=True,
		)

	for pr_name, rows in wanted.items():
		ret = make_return_doc("Purchase Receipt", pr_name)
		ret.items = [i for i in ret.items if i.purchase_receipt_item in rows]
		for item in ret.items:
			src = rows[item.purchase_receipt_item]
			item.qty = -abs(flt(src.qty))
			item.received_qty = item.qty
			item.rejected_qty = 0
			item.stock_qty = -abs(flt(src.stock_qty))
			item.received_stock_qty = item.stock_qty
		if not ret.items:
			continue
		_stamp(ret, pi)
		ret.insert()
		ret.submit()
```

- [ ] **Step 4: Run, expect return tests still failing on cancel** (cancel cascade comes in Task 7): `test_return_cancel_cascades` fails — expected; the other two pass.

- [ ] **Step 5: Commit**

```bash
git add aqrar_ext/aqrar_ext/utils
git commit -m "feat: auto return receipt for return Purchase Invoices

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Cancel cascade

**Files:**
- Modify: `aqrar_ext/aqrar_ext/utils/auto_grn.py`, `aqrar_ext/aqrar_ext/utils/test_auto_grn.py`, `aqrar_ext/hooks.py`

- [ ] **Step 1: Failing tests** — append:

```python
class TestCancelCascade(AutoGrnTestCase):
	def test_cancel_pi_cancels_auto_receipt(self):
		pi = self.make_pi()
		pr_name = linked_receipts(pi.name)[0].name
		pi.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)

	def test_cancel_blocked_when_stock_already_sold(self):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		pi = self.make_pi(qty=10)
		create_delivery_note(item_code=STOCK_ITEM, qty=10, warehouse=WAREHOUSE, company=COMPANY,
			cost_center="_Test Cost Center - _TC", expense_account="_Test Account Cost for Goods Sold - _TC")
		with self.assertRaises(frappe.ValidationError):
			pi.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 1)
```

- [ ] **Step 2: Run, expect FAIL** (receipt stays docstatus 1).

- [ ] **Step 3: Implement** — append to `auto_grn.py`:

```python
def cancel_auto_grn(doc, method=None):
	"""before_cancel: cancel the receipts this invoice created.

	Must be before_cancel, not on_cancel: Frappe runs check_no_back_links_exist
	(the auto PR links to this PI) before on_cancel, so cancelling there is too late.
	Each PR is cancelled with flags.ignore_links = True.

	Runs whether or not the setting is still on — a marker means we created it.
	The app's existing Purchase Receipt before_cancel guard still applies, so if
	the stock was already sold the whole PI cancel is blocked.
	"""
	for name in frappe.get_all(
		"Purchase Receipt", filters={MARKER_FIELD: doc.name, "docstatus": 1}, pluck="name"
	):
		pr = frappe.get_doc("Purchase Receipt", name)
		pr.flags.ignore_links = True
		pr.cancel()
```

- [ ] **Step 4: Register in `hooks.py`.** Add to the Purchase Invoice dict: `"before_cancel": _AUTO_GRN_CANCEL_HOOK,`. Frappe runs `check_no_back_links_exist` (the auto PR links to the PI via `custom_auto_grn_invoice`) before `on_cancel`, so cancelling the PRs there is too late; `cancel_auto_grn` therefore runs in `before_cancel` and cancels each marker PR with `pr.flags.ignore_links = True`.

- [ ] **Step 5: Run the whole module, expect all PASS** (Tasks 2–7).

```bash
cd ~/Developer/frappe-bench
bench --site aqrar-test.local run-tests --app aqrar_ext --module aqrar_ext.aqrar_ext.utils.test_auto_grn
```

- [ ] **Step 6: Regression-check the app's existing PR/PI hooks**

```bash
bench --site aqrar-test.local run-tests --app aqrar_ext
```
Expected: no new failures versus a baseline run on `develop` (`git stash` / branch compare if any appear).

- [ ] **Step 7: Commit**

```bash
git add aqrar_ext/hooks.py aqrar_ext/aqrar_ext/utils
git commit -m "feat: cancel auto-created receipts when the Purchase Invoice is cancelled

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs and UAT hand-off

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a row** to the "What is implemented" table (after the CR-035 row):

```markdown
| — | Purchase Invoice auto-creates and submits the Purchase Receipt (GRN); the invoice never updates stock. Backdated to the system start date for the first 90 days, then PI date − 90 days. Returns and cancels cascade. Off by default | `aqrar_ext/utils/auto_grn.py`, `Aqrar Settings` (Auto GRN section), `setup_data.py` (`custom_auto_grn_invoice`) |
```

- [ ] **Step 2: Commit**

```bash
git add README.md && git commit -m "docs: README row for Purchase Invoice auto-GRN

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: UAT checklist** (run on a copy of production, never prod first). Not automated because they depend on real masters:
  1. Enable the setting. Submit a PI with 2 stock rows + 1 non-stock row: one PR, 2 rows, correct warehouses, dated 2026-09-01.
  2. PI with a **Valuation**-category tax (landed cost): PR and PI GL still reconcile (`Stock Received But Not Billed` nets to zero).
  3. PI linked to a Purchase Order: PO `per_received` updates.
  4. Multi-currency PI: PR conversion rate matches.
  5. Submit as a non-Stock user: clear permission error, PI stays draft.
  6. Backdated PR on an item with later stock movements: confirm repost completes (watch the Repost Item Valuation queue).
  7. Final GRN (CR-001) on an auto PR: note that the PI rows still point at the cancelled PR — known, out of scope.

---

## Self-review against the spec
- Date rule A → Task 2 (+ cutoff boundary tests). ✔
- Inside PI submit, rollback on failure → Task 5 (`test_failure_rolls_back_invoice_submit`). ✔
- Rows with existing PR link skipped; `update_stock` reset; rows without link auto-PR'd → Tasks 4, 5. ✔
- Returns handled; non-stock skipped → Tasks 5, 6. ✔
- Cancel cascade (`before_cancel`, `ignore_links`) + consumed-stock block → Task 7. ✔
- Settings / marker / hooks / README → Tasks 1, 3, 4, 5, 7, 8. ✔
- Ships disabled → Task 1 (`"default": "0"`). ✔
- Names consistent across tasks: `MARKER_FIELD`, `get_grn_posting_date`, `get_grn_date_for`, `force_no_update_stock`, `create_auto_grn`, `cancel_auto_grn`, `_create_forward_grn`, `_create_return_grn`, `_link_rows`, `_stamp`. ✔

## Open item (needs a decision before enabling in production)
Rule A applied literally can date a receipt **before the system start date** (a PI dated before the cutoff but entered after it, e.g. PI 2026-10-15 entered 2026-12-15 → GRN 2026-07-17). Test `test_after_cutoff_literal_rule_even_before_start` pins the literal behaviour. If that is unwanted, change `get_grn_posting_date`'s last line to `max(start, …)` and flip that test.
