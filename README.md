### Aqrar EXT

Custom app for Aqrar (KSA multi-location trading business), implementing the
change requests agreed in the 2026-04-23 implementation meeting.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site $SITE install-app aqrar_ext
bench --site $SITE migrate      # required: provisions Custom Fields + workflows
```

`bench migrate` is not optional. The app's Custom Fields are created
idempotently by `setup_data.create` (the `after_migrate` hook), not shipped as
fixtures, so an implementer's local tweaks to a field are never overwritten.
Installing without migrating leaves those fields absent.

### What is implemented

| CR | Feature | Where |
|----|---------|-------|
| CR-005 | Multi-select item picker with running search, per-item qty, stock badge | `public/js/item_selector.js`, `item_selector_hook.js` |
| CR-006 | Per-customer last-sold price column + Price Assist panel | `public/js/customer_price_history.js`, `api/price_history.py` |
| CR-007 | Payment popup on save → auto Payment Entry; partial payment for credit customers | `public/js/sales_invoice_pos_total_popup.js`, `api/sales_invoice.py` |
| CR-008 | Customer statement report + PDF | `aqrar_ext/report/customer_statement/` |
| CR-009 | Day-close reports | `aqrar_ext/report/dcr_report/`, `daily_report_combined/` |
| CR-010 | Stock Entry naming-counter repair | `patches/fix_stock_entry_naming_series.py` |
| CR-011 | Enhanced Stock Ledger (company / transaction type / item filters) | `aqrar_ext/report/stock_ledger_report/` |
| CR-012 | Aqrar Delivery Note print format (no prices) | `fixtures/print_format.json` |
| CR-013, CR-029 | Material Request fulfilment counter, close/reopen, urgent flag | `public/js/material_request_custom.js`, `events/material_request.py` |
| CR-014 | Credit-note sign handling (positive entry, negative posting) | `public/js/sales_invoice_return.js`, `overrides/sales_invoice.py` |
| CR-015, CR-019 | Price List Bulk Editor, branch price lists, minimum selling rate | `aqrar_ext/page/price_list_bulk_editor/`, `aqrar_ext/utils/pricing.py` |
| CR-016 | Print preview on save | `public/js/auto_print_preview.js` |
| CR-017 | Stock Entry / Material Request / Expense Claim workflows | `fixtures/workflow*.json`, `setup_data.py` |
| CR-018 | Project field permissions | `fixtures/custom_docperm.json` |
| CR-020, CR-030 | Item Group default naming series; TM- series for customer-specific items | `overrides/item.py`, `setup_data.py` |
| CR-021 | Item-create / price-update notifications + sound toggle | `fixtures/notification.json`, `public/js/notification_sound.js` |
| CR-022 | Previous / next navigation on Sales Invoice | `public/js/sales_invoice_nav.js` |
| CR-023 | Commission Journal Entry linked to its Sales Invoice | `api/commission.py`, `public/js/journal_entry_commission.js` |
| CR-024 | Item name / code / description display toggle (preview and print) | `api/print_utils.py`, `aqrar_ext/utils/print_helpers.py`, Aqrar Settings |
| CR-026 | Payment terms template from Customer | `aqrar_ext/overrides/sales_invoice.py` |
| CR-027 | Mandatory + unique bank reference on Payment Entry | `overrides/payment_entry.py` |
| CR-028 | `update_stock` policy per role (Branch User issues via Delivery Note) | `overrides/sales_invoice.py` |
| CR-031 | Default UOM locked after first stock movement, audited admin override | `overrides/item.py`, `public/js/item.js` |
| CR-033 | Pending-approval queue + desk badge | `aqrar_ext/report/work_flow_approval/`, `public/js/workflowapproval.js` |
| CR-035 | Transaction UOM dropdown limited to the item's own UOMs | `public/js/item_uom_filter.js`, `api/queries.py` |

### Not implemented (deliberately)

These need a business decision or belong to another app. They are listed so no
one assumes they are done:

- **CR-001 (Final GRN valuation back-fill)** — the client flow now creates the
  replacement receipt and retires the original safely, but it does **not**
  repost the landed cost into Sales Invoices that already consumed the
  zero-rate stock. The CR itself flags the valuation method as an open question
  for finance.
- **CR-003 / CR-036 (ZATCA clearance and sequence-gap enforcement)** — belongs
  in `ksa_compliance`, not here. Note that CR-003 ("no invoice left in draft")
  conflicts with CR-016 (preview on save) and with the payment popup, which
  both rely on a saved draft.
- **CR-017, Journal Entry and Payment Entry workflows** — the `workflow_state`
  fields and the approval queue support them, but no active workflow is
  shipped. Turning one on changes every payment on a live site, so it must be
  configured per site, deliberately.
- **CR-025 (mobile PoS)** — explicitly parked as Phase 2 in the CR document.
- **CR-032 (returning in a sub-UOM of the sold UOM)** — blocked on the open
  question of which rate to apply.
- **CR-038 (permission matrix document)** — a documentation deliverable.

### Fixtures — two traps worth knowing

`frappe.utils.fixtures.import_fixtures` imports **every** `.json` in
`fixtures/`, ignoring the `fixtures` list in `hooks.py` (that list only governs
*export*), and it imports them in plain alphabetical order.

1. A stale `fixtures/mode_of_payment.json` therefore synced even though it was
   never declared. On a site with `ksa_compliance` it aborted the whole migrate
   (`MandatoryError: [Mode of Payment, Cash]: custom_zatca_payment_means_code`),
   and had it succeeded it carried `"accounts": []`, which would have wiped the
   default Cash/Bank account off every listed mode — the field the payment
   popup reads. The file is gone; `setup_data.check_expected_modes_of_payment`
   now only warns when an expected mode is missing.
2. `workflow.json` sorts before `workflow_action_master.json` and
   `workflow_state.json`, so on a fresh site the workflows import before the
   states they link to. `setup_data.before_migrate` seeds those two masters
   first.

`DCR Report` and `Daily Report Combined` both answer CR-009 and overlap. Both
are kept until Aqrar confirms which one is in use (an open question in the CR
document); see the note at the top of each file before changing either.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/aqrar_ext
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.

### License

mit
