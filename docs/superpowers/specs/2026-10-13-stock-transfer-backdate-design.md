# Stock Transfer (Material Transfer) auto-backdate — design

Date: 2026-10-13 · App: `aqrar_ext` · Source: client requirement PDF "Independent Backdated Stock Transfer Setup in ERPNext"

## Goal
Users never backdate a Stock Entry (Purpose = Material Transfer) by hand. When the company's
switch is on, the posting date is set automatically:

    final date = max(posting date - Stock Transfer Backdate Days, Stock Transfer System Start Date)

The start date is always the floor (the same protection the Purchase Invoice auto GRN got after
UAT: start 01-09, 30 days, date 29-09 gives 01-09, never 30-08). A transfer posted before the
start date is moved forward to it.

## Independent of the Purchase Invoice auto GRN
Own fields, own function, no shared state, auto GRN code untouched. Changing one never moves the
other (tested both ways, including switching one off).

| Company field (section "Stock Transfer Backdate") | Default |
|---|---|
| `custom_stock_transfer_backdate_enabled` — Enable Backdated Stock Transfer | off |
| `custom_stock_transfer_start_date` — Stock Transfer System Start Date (required when enabled) | — |
| `custom_stock_transfer_backdate_days` — Stock Transfer Backdate Days (>= 0) | 0 |

Plus `Stock Entry.custom_stock_transfer_backdated` (read-only, no_copy): "already dated".

## Scope
Purpose = Material Transfer only, including the receiving entry of an in-transit transfer (it is a
Material Transfer too). Material Receipt, Issue, Manufacture, Repack, Send to Subcontractor are
untouched. No Purchase Receipt or other document is created: the Stock Entry itself moves the stock.

## When the date is set — and why not at submit
`before_validate`, on the first save of a draft (or on submit, for a draft saved before the switch
was turned on), marked by the `custom_stock_transfer_backdated` flag so it happens **once**:
re-saves never subtract the days again, a date the user edits afterwards is respected, and changing
the company's days later does not move a draft already dated.

The first design applied it in `before_submit`. That is wrong: ERPNext computes a transfer's
valuation rates (and available qty, batch/serial availability) in `validate` as of the posting
date. Moving the date afterwards leaves the target leg valued on the ORIGINAL date while the ledger
posts both legs on the backdated one. Reproduced: source leg out at 10 per unit, target in at
66.67, +566.67 of stock value created from nothing (and +138.1 in the unit test). Set before
validate, everything is computed on the final date exactly as if the user had typed it, and the
transfer is valued identically to one entered by hand on that date (tested).

Note `bench run-tests` runs with `frappe.flags.in_test`, which hides this defect; the valuation test
switches it off for the transfer, as production runs.

ERPNext's own `validate_posting_time` resets the date to "now" unless "Edit Posting Date and Time"
is ticked, so the hook ticks it. The hook runs first in `before_validate`, ahead of the app's
source/target warehouse qty hook, which therefore sees the final date.

## Audit
When the date moves: an Info comment on the entry (ISO dates: "posting date 2026-10-07 changed to
2026-09-07 (30 days back, System Start Date 2026-09-01)") and an on-screen message.

## Behaviour to know
- ERPNext still checks the source stock **on the backdated date**: a transfer is refused if the
  source warehouse had no stock then (tested).
- A backdated entry makes ERPNext re-value later movements of the item/warehouse. In production
  the repost is queued and run by the scheduler (it only runs inline in tests). Keep the days small.
- Entries submitted before the switch was turned on are not touched.

## Hooks (`hooks.py`)
- Stock Entry `before_validate`: `apply_stock_transfer_backdate` (first, before the warehouse qty hook)
- Stock Entry `on_update`: `record_stock_transfer_backdate` (attaches the comment once the entry exists)
- Company `validate`: `validate_company_stock_transfer_backdate`

## Tests (`utils/test_stock_transfer_backdate.py`, 33)
Date rule (normal, boundary, exactly on the start date, one day after, before the start, 5/10/30/90
days, 0 days); enabled/disabled; Material Receipt and Issue untouched; once-only (3 saves + submit);
manual edit respected; draft made before the switch; later change of days; audit comment; refused
without source stock on the new date; valuation equals a hand-entered transfer (production mode);
in-transit receipt; submitted entry not re-dated; independence from the GRN values both ways;
Company validation.
