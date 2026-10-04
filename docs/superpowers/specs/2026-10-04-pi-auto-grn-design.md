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
| Registration | `hooks.py` → `doc_events["Purchase Invoice"]`: `validate` += `force_no_update_stock`; new `before_submit` = `create_auto_grn`; new `on_cancel` = `cancel_auto_grn` (cancel cascade) |
| Settings | `Aqrar Settings` += `auto_grn_enabled` (Check, default 0), `auto_grn_system_start_date` (Date, 2026-09-01), `auto_grn_backdate_days` (Int, 90) |
| Marker | Custom Field `Purchase Receipt-custom_auto_grn_invoice` (Link → Purchase Invoice, read-only, no_copy) via `setup_data.CUSTOM_FIELDS` |
| Tests | `aqrar_ext/aqrar_ext/utils/test_auto_grn.py` (pure date fn) + integration tests |

Feature ships **disabled**; enable per site after UAT.

## Flow
**validate** — if enabled and PI has any stock item row: `doc.update_stock = 0`.

**before_submit** — skip if disabled. Select rows: `is_stock_item` and no `pr_detail`.
No rows → return.
1. Build PR with ERPNext `make_purchase_receipt(PI.name)` mapper, restricted to selected rows
   (carries supplier, qty, rate, UOM, taxes, cost center, project; `warehouse` = PI row
   warehouse = Accepted Warehouse; `received_qty = qty`).
2. `set_posting_time = 1`, `posting_date = get_grn_posting_date(today)`, set marker field.
3. `insert()` + `submit()` under the submitting user's permissions (no `ignore_permissions`).
4. Write `purchase_receipt` / `pr_detail` onto the matching PI rows in memory so PI's own GL
   clears Stock Received But Not Billed and PR billed-amount updates. Without this the PI
   would book stock directly and leave GRNI dangling.

**Return PI** (`is_return`, `return_against`): per original PR referenced by the original PI
rows, create a return PR via ERPNext `make_return_doc("Purchase Receipt", …)` with the
returned qty, same date rule, link onto return PI rows. Original PI with no PR (pre-feature
invoice) → skip rows with a message, do not fail. Existing PR hooks (`flip_return_quantities`,
`apply_uom_aware_returns`) run on the generated return PR; tests must cover this.

**on_cancel** — cancel PRs carrying the marker for this PI. Existing
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
- Landed-cost vouchers, Purchase Order linkage changes: not touched.

## Test plan
Date boundaries · submit creates 1 submitted PR with right warehouse/qty/rate/date ·
`update_stock` forced 0 · non-stock rows skipped · linked rows skipped · return PI → return
PR · cancel cascade · cancel blocked when consumed · rollback when PR creation fails ·
feature disabled = no-op.
