# Purchase Invoice → auto Purchase Receipt (GRN) — design

Date: 2026-10-04 · App: `aqrar_ext` (branch `develop`) · Site: aqrar-prod.enfonoerp.com

## Goal
Submitting a Purchase Invoice (PI) automatically creates and submits the Purchase
Receipt (PR / GRN) that books the stock. The PI itself never updates stock.

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
| Registration | `hooks.py` → `doc_events["Purchase Invoice"]`: `before_validate` += `force_no_update_stock`; `on_submit` += `create_auto_grn`; `before_cancel` = `cancel_auto_grn` |
| Settings | `Aqrar Settings` += `auto_grn_enabled` (Check, default 0), `auto_grn_system_start_date` (Date, 2026-09-01), `auto_grn_backdate_days` (Int, 90) |
| Marker | Custom Field `Purchase Receipt-custom_auto_grn_invoice` (Link → Purchase Invoice, read-only, no_copy) via `setup_data.CUSTOM_FIELDS` |
| Tests | `aqrar_ext/aqrar_ext/utils/test_auto_grn.py` (pure date fn) + integration tests |

Feature ships **disabled**; enable per site after UAT.

## Flow
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

**Return PI** (`is_return`, `return_against`): Return PI rows already carry the original row's `purchase_receipt`/`pr_detail` (copied by ERPNext). Group the stock rows by that original PR; only when the original PR carries our marker, build a return PR with `make_return_doc("Purchase Receipt", pr)` limited to those rows and the returned qty. Otherwise skip with a message. Original PI with no PR (pre-feature
invoice) → skip rows with a message, do not fail. Existing PR hooks (`flip_return_quantities`,
`apply_uom_aware_returns`) run on the generated return PR; tests must cover this.

**before_cancel** — cancel PRs carrying the marker for this PI (with `pr.flags.ignore_links = True`). Frappe runs `check_no_back_links_exist` (the auto PR links to the PI via `custom_auto_grn_invoice`) before `on_cancel`, so cancelling the PRs there is too late; `cancel_auto_grn` therefore runs in `before_cancel` and cancels each marker PR with `pr.flags.ignore_links = True`. Existing
`block_cancel_if_consumed` still applies: if the stock was already sold, cancelling the PI is
blocked with its message (intended — stock cannot vanish under sales).

## Date function
`get_grn_posting_date(today, settings) -> date`, pure, no DB. Uses `getdate`, `add_days`.
Tested: 2026-11-29 → 2026-09-01; 2026-11-30 → PI date − 90; PI date before start date.

## Safety
- Idempotent: linked rows skipped; marker prevents duplicate PR on retry.
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
- Backdated PRs trigger valuation repost for later movements of the item/warehouse, inside the submit transaction.
- Landed-cost vouchers, Purchase Order linkage changes: not touched.

## Test plan
Date boundaries · submit creates 1 submitted PR with right warehouse/qty/rate/date ·
`update_stock` forced 0 · non-stock rows skipped · linked rows skipped · return PI → return
PR · cancel cascade · cancel blocked when consumed · rollback when PR creation fails ·
feature disabled = no-op.
