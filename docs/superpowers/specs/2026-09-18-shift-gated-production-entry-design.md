# Design: Shift-Gated vs Stock-Only Production Entries

Date: 2026-09-18
Status: Approved for implementation planning
Source: brainstorming session (Approach 1 — Shift as the gate)

## Purpose

Distinguish **Shift-based** Production Entries from **Stock-only** Production
Entries. Some users need Manufacture or Joint LH/RH stock movements without
recording production metrics, workstation, operators, rejection, or losses.
Selecting Shift enables that full capture path; leaving Shift blank must not make
those fields mandatory.

## Locked decisions

1. **Gate:** `custom_pea_shift` presence. No new checkbox or Stock Entry Type.
2. **UI without Shift:** shift-dependent capture fields are **hidden**.
3. **Scope:** both normal **Manufacture** and **Joint LH/RH Production**.
4. **Mandatory when Shift is set:** Workstation, Operator, Actual Start, Actual
   End, Standard SPM > 0. Total Press Strokes stays shift-gated and optional
   (assembly and other non-press operations may have zero strokes).
5. **Clearing Shift:** clears gated field values (client and server).
6. **Rework** stays out of scope (already non-shift).

## Domain language

**Shift-based Production Entry**  
A Manufacture or Joint Production Entry with `custom_pea_shift` set. Captures
time, resources, losses, rejection, strokes, and metrics in addition to stock.
_Avoid_: Full production entry, supervised entry

**Stock-only Production Entry**  
A Manufacture or Joint Production Entry with no Shift. Records inventory from
BOM(s) and fetch-items only. Excluded from Shift summaries and Production Date
Range (already true via missing Shift / non-Completed Shift rules).
_Avoid_: Non-shift manufacturing entry, simple stock manufacture

Add both terms to `CONTEXT.md` during implementation.

## Behavior

### Always visible on Manufacture / Joint (not Rework)

- `custom_pea_shift` (optional)
- Stock / BOM UI:
  - Manufacture: native BOM fields, FG completed qty, fetch items
  - Joint: operation, LH/RH BOMs and gross quantities, joint fetch items
- Items table and native stock fields

### Visible only when Shift is set

Hidden when Shift is empty; cleared when Shift is cleared:

- Planned start / end (still auto-filled from Shift when linked)
- Actual start / end and helper date/time inputs
- Workstation, Operator, Standard SPM
- Unplanned losses
- Rejection qty / breakup / rework qty (Manufacture)
- Side rejection quantities (Joint)
- Total Press Strokes, Die Tool Item (Joint), metrics section (duration, SPM,
  efficiency, die-tool health)

### Mandatory when Shift is set

Client `toggle_reqd` and server `frappe.throw`:

| Field | Rule |
| --- | --- |
| Workstation | required |
| Operator | required |
| Actual Start | required |
| Actual End | required |
| Standard SPM | must be > 0 |

Total Press Strokes remains visible in shift mode but is **not** required to be
> 0 (assembly and other non-press operations). If the user enters a value, it
must not be negative; existing die-tool counter logic already no-ops when
strokes ≤ 0.

Rejection and unplanned losses remain optional unless the user fills them (then
existing row validations apply).

## Server design

Primary seam: `validate_stock_entry` in
`production_entry_app/overrides/stock_entry_hooks.py`.

Introduce `is_shift_based_production_entry(doc)`:

- true when the entry is a production overlap entry (Manufacture, or Joint
  Repack) **and** `custom_pea_shift` is set;
- false otherwise (including Rework and stock-only production).

### Without Shift (stock-only)

Skip shift-capture validations and mutations:

- Standard SPM require / sync-from-workstation require path
- Total strokes default-to-FG (do not invent strokes on stock-only entries)
- Actual-time window checks (already no-op without planned window)
- Workstation / operator / downtime overlap (already gated on Shift today)
- Rejection apply / breakup require paths that only matter when rejection UI is
  used (fields cleared → qty 0 → existing no-op)
- Entry metrics (already no-op without actual times)

Still run stock / BOM / joint item-row validation required to submit inventory.

If Shift is empty on validate, clear gated field values server-side (defense in
depth vs client-only clear).

### With Shift (shift-based)

Keep current Shift defaults and existing checks; **add** the mandatory-field
checks listed above (Workstation, Operator, Actual Start/End, Standard SPM > 0).

Total Press Strokes: do **not** require > 0. Do **not** coerce empty/zero to
`fg_completed_qty` in a way that invents strokes for assembly — leave blank/zero
unless the user enters a value (negative values still rejected if that check
already exists).

### Submit side effects

Die-tool counter update stays as today: no-ops when strokes ≤ 0, so stock-only
paths do not bump counters.

Reports unchanged: Production Date Range and Shift summaries already key on
Shift.

## Client design

Primary seam: `production_entry_app/public/js/stock_entry.js` visibility helpers
(covered by `tests/unit/stock-entry-visibility.test.js`).

- Split PEA fields into always-on (`custom_pea_shift` + stock/BOM) vs
  shift-gated lists/sections.
- `_apply_manufacture_visibility`: show gated sections only when Shift is set;
  `toggle_reqd` for the mandatory set when Shift is set.
- On Shift clear: clear gated scalars and tables (same spirit as existing shift /
  rework clear helpers).

## Testing

| Seam | Coverage |
| --- | --- |
| `validate_stock_entry` | Stock-only Manufacture and Joint save/validate without SPM/workstation; Shift-based requires the mandatory set; Shift-based with zero Total Press Strokes is allowed |
| Client visibility | Gated fields hidden/optional without Shift; shown/required with Shift; clear-on-clear |
| E2E | One stock-only Manufacture path: BOM + fetch + submit without Shift capture fields |

## Out of scope

- New Stock Entry Type or “shift-based” checkbox
- Rework behavior changes
- Report formula changes beyond existing “no Shift → not in shift-dated reports”
- Making rejection or losses mandatory in shift mode

## Success criteria

1. User can submit Manufacture or Joint stock from BOM without selecting Shift,
   with no PEA capture-field validation failures.
2. Selecting Shift reveals capture fields and blocks save until Workstation,
   Operator, Actual Start/End, and Standard SPM > 0 are set. Zero Total Press
   Strokes remains allowed (e.g. assembly).
3. Clearing Shift hides and clears those capture fields.
4. Existing Shift-based and Rework flows keep passing their tests.
