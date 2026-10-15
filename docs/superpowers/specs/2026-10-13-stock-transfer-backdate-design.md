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

## Edge cases handled (found in review, each has a test that fails without the fix)
- **Draft left on the rule's own date**: "Edit Posting Date and Time" is always ticked when the rule
  applies, otherwise ERPNext resets the date to "now" when the draft is submitted days later.
- **Several transfers on the floor date**: all get posting time 23:59:59. Made on different days they
  would otherwise sort by real time of day, and a later transfer could sort before the earlier one it
  depends on and be refused for lack of stock.
- **In-transit receipt**: never dated before its outgoing entry (ERPNext refuses stock that has not
  left transit); when dates tie it takes the outgoing entry's time.
- **Stock freeze** (`Stock Settings` freeze date, and the rolling "freeze older than N days") counts as
  a floor too: a transfer is dated on the first open day instead of being refused for the user to
  re-date by hand. Closed *accounting* periods are not considered (they do not govern stock postings).
- **Data Import** (`frappe.flags.in_import`): historical entries are not re-dated.

## Audit
When the date moves: an Info comment on the entry (ISO dates: "posting date 2026-10-07 changed to
2026-09-07 (30 days back, System Start Date 2026-09-01)") and an on-screen message.

## Behaviour to know
- ERPNext still checks the source stock **on the backdated date**: a transfer is refused if the
  source warehouse had no stock then (tested).
- A backdated entry makes ERPNext re-value later movements of the item/warehouse. In production
  the repost is queued and run by the scheduler (it only runs inline in tests). Keep the days small.
- Entries submitted before the switch was turned on are not touched.
- **Business risk — recently received stock cannot be transferred.** The source warehouse must hold
  the stock on the *backdated* date, so goods received within the last N days are refused by ERPNext.
  The two settings are independent by requirement: if Stock Transfer Backdate Days is larger than the
  auto-GRN backdate days, freshly received goods (dated back by the GRN rule) are refused for the gap.
  Choose the transfer days with that in mind (smaller than the GRN days is safe).
- A draft made before the switch and dated at its submit keeps the source/target qty snapshot of its
  draft date (the warehouse qty hook skips submitted entries). Display only.
- Outside this change: the app's "Stock Transfer Approval" workflow fixture has state *Rejected* with
  `doc_status` 1 (it would submit a rejected transfer). The workflow is not active; fix before enabling.

## Hooks (`hooks.py`)
- Stock Entry `before_validate`: `apply_stock_transfer_backdate` (first, before the warehouse qty hook)
- Stock Entry `on_update`: `record_stock_transfer_backdate` (attaches the comment once the entry exists)
- Company `validate`: `validate_company_stock_transfer_backdate`

## Tests (`utils/test_stock_transfer_backdate.py`, 40)
Date rule (normal, boundary, exactly on the start date, one day after, before the start, 5/10/30/90
days, 0 days); enabled/disabled; Material Receipt and Issue untouched; once-only (3 saves + submit);
manual edit respected; draft made before the switch; later change of days; audit comment; refused
without source stock on the new date; valuation equals a hand-entered transfer (production mode);
in-transit receipt (real receipt, both on the floor, hand-edited outgoing); submitted entry not re-dated;
floor ordering; stock freeze (date and rolling days); import; independence from the GRN values both
ways; Company validation. Every test is isolated by a savepoint.

## Revision 2026-10-15 (client UAT feedback)

1. **Re-saves.** The first version dated a draft once and then respected any date typed afterwards, so
   a user who moved the date of an already-backdated draft got it back un-backdated. Now, while
   "Stock Transfer Backdate Applied" is ticked: an untouched re-save keeps the date (no second
   subtraction); a re-save after the user typed another posting date dates THAT date again
   (start 01-09, 30 days: created 14-10 -> 14-09; typed 20-10 -> 20-09; floored at the start date).
   Changing the company's days alone still does not move a dated draft.
2. **Untick by an authorised role.** Stock Manager / System Manager (`OVERRIDE_ROLES`) can untick the
   flag on a saved Draft (the JS `stock_entry_backdate_override.js` unlocks the read-only field; the
   server refuses a tick change by anyone else). Unticked: the posting date stays exactly as entered,
   same-day transfers included, on every later save. Ticked again: dated on the next save. Who and when:
   `custom_stock_transfer_unticked_by` / `_on` (read-only, shown once set) plus an Info comment on the
   entry for every untick and re-tick. A brand-new entry cannot be unticked before its first save
   (unticked and "not dated yet" look the same on a new entry): save once, then untick.

## Revision 2026-10-15 (2): the untick role is a Company setting
Replaces the fixed Stock Manager / System Manager of revision 1. Company field
`custom_stock_transfer_untick_role` ("Role Allowed to Untick Backdate", Link to Role, in the Stock Transfer
Backdate section). Only users holding that role can tick / untick `Stock Transfer Backdate Applied` on a
saved Draft; everybody else, Stock Manager and System Manager included, sees it read-only and the server
refuses the change. Empty = nobody (even Administrator is refused on the server and the box stays
read-only). The role is read from the Company on every form refresh and every save, so a change applies at
once, with no restart. Administrator holds every role in Frappe, so it passes whenever a role is set.
Logging (who / when fields, timeline comments) and every other behaviour are unchanged.
