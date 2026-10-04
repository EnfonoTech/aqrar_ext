# Purchase Invoice → auto Purchase Receipt (GRN) — design

Date: 2026-10-04 · App: `aqrar_ext` (branch `develop`) · Site: aqrar-prod.enfonoerp.com

## Goal
Submitting a Purchase Invoice (PI) automatically creates and submits the Purchase
Receipt (PR / GRN) that books the stock. The PI itself does not update stock, except a
standalone debit note (no `return_against`) and a return against a pre-feature PI that had
`update_stock = 1`; those move the stock on the PI.

## Decisions (agreed with requester)
1. **Date rule (A).** `system_start = 2026-09-01`, `cutoff = start + 90 days = 2026-11-30`.
   - `today < cutoff` → PR posting date = `2026-09-01` (regardless of PI date).
   - `today >= cutoff` → PR posting date = PI posting date − 90 days.
2. **Inside PI submit.** PR is created in `before_submit`, same transaction. Any failure
   throws and rolls the PI submit back. No background queue.
3. **Existing PR link / `update_stock`.** Rows already carrying `purchase_receipt` +
   `pr_detail` are skipped. `update_stock` is silently reset to 0 on validate. Rows with no
   link get the auto-PR.
4. **Returns handled; non-stock items skipped.**

## Components
Follows existing app conventions (checked in repo): Custom Fields come from
`setup_data.CUSTOM_FIELDS`, not fixtures; hook functions live in `aqrar_ext/aqrar_ext/utils/`
and are registered as `_X_HOOK` constants in `hooks.py`; settings live in the
`Aqrar Settings` Single DocType.

| Piece | Where |
|---|---|
| Hook logic | new `aqrar_ext/aqrar_ext/utils/auto_grn.py` |
| Registration | `hooks.py` → `doc_events["Purchase Invoice"]`: `before_validate` += `force_no_update_stock`; `on_submit` += `create_auto_grn`; `on_cancel` = `cancel_auto_grn` |
| Settings | `Aqrar Settings` += `auto_grn_enabled` (Check, default 0), `auto_grn_system_start_date` (Date, 2026-09-01), `auto_grn_backdate_days` (Int, 90) |
| Marker | Custom Field `Purchase Receipt-custom_auto_grn_invoice` (Link → Purchase Invoice, read-only, no_copy) via `setup_data.CUSTOM_FIELDS` |
| Tests | `aqrar_ext/aqrar_ext/utils/test_auto_grn.py` (pure date fn) + integration tests |

Feature ships **disabled**; enable per site after UAT.

## Flow
**before_validate** — if enabled and the PI has any stock item row: `doc.update_stock = 0`.
Must be before ERPNext's own validate, which derives each row's expense account from `update_stock`.
Exception: a return against a PI that moved stock itself (`update_stock = 1`, pre-feature)
keeps `update_stock`, so the return moves the stock back itself (there is no auto PR to return);
so does a standalone debit note (`is_return` with no `return_against`).

**on_submit** (runs after ERPNext's own on_submit, inside the same transaction) — skip if
disabled. Select rows: stock item and no `pr_detail`. No rows → return.
1. `make_purchase_receipt(PI.name, args={"filtered_children": [row names]})` — the stock mapper;
   it requires the PI to be docstatus 1, which it is by now.
2. Set `set_posting_time = 1`, `posting_date` per the date rule, `posting_time = 00:00:01`,
   marker field. `insert()` + `submit()` under the user's own permissions.
   The PR's header discount is reset to the share its rows carry on the PI: the sum of their
   `distributed_discount_amount` (prorated for partly received rows), applied on Net Total. The
   mapper would otherwise copy the whole discount onto a PR holding only the stock rows. Not
   `amount - net_amount`: with tax-inclusive VAT that difference also holds the tax. The share
   is used only when the PI itself has a header discount (`discount_amount`, which
   `additional_discount_percentage` also sets): ERPNext writes `distributed_discount_amount`
   only while a discount is set and never clears it, so a discount set then removed, or rows
   copied from a discounted document, leave stale values.
   After insert, the PR's net total (company currency) is compared with the PI stock rows' net
   total. With n rows and one unit of the last currency digit d: up to n·d passes silently; up
   to n·d + 5·d passes and writes an Error Log titled `Auto GRN rounding difference`
   (reference: the Purchase Invoice); beyond that the submit is refused.
3. Link (only rows the PR took in full): write `purchase_receipt` / `pr_detail` onto the PI rows (`frappe.db.set_value` + in
   memory) and call `pi.update_billing_status_in_pr()` so the PR shows as billed.
Accounting: PI's own GL (posted first) debits Stock Received But Not Billed because the rows had
no PR yet; the PR then credits it and debits Stock In Hand. ERPNext supports this order.
Any exception rolls the whole PI submit back.

**Return PI** (`is_return`, `return_against`): Return PI rows already carry the original row's `purchase_receipt`/`pr_detail` (copied by ERPNext). Group the stock rows by that original PR; only when the original PR carries our marker, build a return PR with `make_return_doc("Purchase Receipt", pr)` limited to those rows and the returned qty. Otherwise skip with a message. Original PI with no PR (pre-feature
invoice) → skip rows with a message, do not fail. Existing PR hooks (`flip_return_quantities`,
`apply_uom_aware_returns`) run on the generated return PR; tests must cover this.
Each return PR row takes UOM, conversion factor, qty and stock qty from the return PI row (a
return may change UOM). Its header discount is set the same way as the forward PR's, from the
return PI rows' `distributed_discount_amount` (only when the return PI has its own header
discount), so the return PR's net equals the return PI's.
Its rows' expense account is set to the company's default expense account (else its stock
adjustment account; with neither, the return is refused with a message): a return PR books
"divisional loss" (its net vs the stock value it removes at the original rate) there, and the
copied row would otherwise put it on Stock Received But Not Billed. This arises because ERPNext
gives a return PI its own discount split — e.g. 10 @ 50 less 50, return 2: return PI net -50
(the whole discount), stock out 90, so 40 goes to the expense account and SRBNB nets to zero.
A return against a PI that kept `update_stock` creates no return PR and shows no message.
A debit note with no `return_against` and `update_stock = 0` whose rows point at an auto PR
moves no stock; it shows the orange "return that stock manually" message.
The return PR is never dated before the PR it returns: if the rule
gives an earlier timestamp, the original PR's posting date/time is used (ERPNext only refuses a
strictly earlier one).

**on_cancel** — cancel PRs carrying the marker for this PI, with the PR's normal link check.
Frappe runs the PI's own `check_no_back_links_exist` after `on_cancel`
(`Document.run_post_save_methods`), by when the PRs are cancelled; and the PI is already saved
as cancelled, so its rows do not block the PR. Any other submitted document linked to the PR
(Landed Cost Voucher, manual return PR) blocks the whole PI cancel. Existing
`block_cancel_if_consumed` still applies (not to return PRs: cancelling a return adds stock back): if the stock was already sold, cancelling the PI is
blocked with its message (intended — stock cannot vanish under sales).

## Date function
`get_grn_posting_date(today, settings) -> date`, pure, no DB. Uses `getdate`, `add_days`.
Tested: 2026-11-29 → 2026-09-01; 2026-11-30 → PI date − 90; PI date before start date.

## Safety
- Idempotent: the forward path skips rows that already carry `pr_detail` or are fully
  received (`received_qty`), both written in the same transaction as the PR. The marker is
  used by returns and cancel, not to dedupe the forward path.
- Stock freeze / closed-period checks still apply to the backdated PR — fail loudly.
- Backdating makes ERPNext repost later SLEs for the item/warehouse; acceptable, noted for
  large-history items.
- No raw SQL; `_()` on all user text; `cint/flt/getdate` only.

## Known interactions / out of scope
- **Final GRN (CR-001)** cancels a PR and creates a replacement. A PI row linked to the
  cancelled PR is not re-pointed. Not handled here.
- Existing PIs are untouched; no patch required.
- **Permissions (OPEN product decision):** PI submitters without Purchase Receipt create permission (e.g. Accounts User) get a PermissionError and the PI submit rolls back. Either grant PR create/submit to those roles, or set `ignore_permissions` on the system-created PR.
- Rows with `received_qty > 0` and no `pr_detail` are left unlinked (the PR covers only the remainder).
- A PI stock row with no resolvable warehouse throws a clear error.
- Backdated PRs trigger valuation repost for later movements of the item/warehouse. In production the
  `Repost Item Valuation` is queued and processed by the scheduler (it runs inline only in tests).
- Landed-cost vouchers, Purchase Order linkage changes: not touched.
- Fixed-asset rows on a PI that also has stock items get `update_stock` forced off but are never
  put on a receipt, so no Asset is created. Out of scope (trading business).
- **Consumption guard vs cancel (OPEN product decision):** `block_cancel_if_consumed` blocks PI
  cancel/amend for items that sell regularly, because it compares by item + warehouse + date, not
  by lot.
- **Final GRN on auto receipts (OPEN product decision):** `cancel_for_final_grn` does not set
  `ignore_links`, so it errors on an auto receipt whose rows now link back to the PI.

## Test plan
Date boundaries · submit creates 1 submitted PR with right warehouse/qty/rate/date ·
`update_stock` forced 0 · non-stock rows skipped · linked rows skipped · return PI → return
PR · cancel cascade · cancel blocked when consumed · rollback when PR creation fails ·
feature disabled = no-op.
