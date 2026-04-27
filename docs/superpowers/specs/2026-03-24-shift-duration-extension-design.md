# Shift Duration Extension Design

Date: 2026-03-24
Branch: `spec/shift-duration-extension`

## Goal

Allow supervisors to revise `shift_duration` while a Shift is `Running` so the Shift can be extended mid-shift when production continues past the original plan. The revised duration must immediately recalculate Shift-derived scheduling data and all user-visible metrics that depend on the Shift definition.

## Requirements

- A `Running` Shift may change `shift_duration`.
- Saving the revised duration must recompute:
	- `planned_end_time`
	- `shift_end_date`
	- Shift `planned_losses`
	- Shift summary payloads and cached metrics
	- running timeline window
	- report denominators that depend on `shift_duration` or Shift planned losses
- `planned_losses` remain server-generated and read-only while the Shift is `Running`.
- `JH Activity` must use a fixed absolute slot of `10:00 AM - 10:10 AM`.
- Fixed planned-loss rows are only created when their clock window overlaps the active Shift window. If `10:00 AM - 10:10 AM` falls outside the Shift window, no `JH Activity` row is created.
- Submitted Stock Entries must not be rewritten when the Shift duration changes.
- Draft or future Stock Entries linked to the Shift should pick up the revised planned window through normal validation/save flows.

## Current State

### Shift locking

`Shift._validate_field_locking()` currently blocks `planned_losses` edits in `Running` state and blocks all edits in `Completed` or `Cancelled` state. This effectively prevents mid-shift duration changes even though downstream logic already derives planned end and metrics from Shift fields.

### Planned loss generation

Planned losses are regenerated when `shift_duration`, `planned_start_time`, or `shift_date` changes. The current rules mix:

- start-relative rows in `_SHIFT_START_LOSSES`
- fixed clock-based rows in `_FIXED_TIME_BREAKS`

`JH Activity` currently behaves as a relative row and must be changed to a fixed absolute row.

### Shift-derived consumers

The following user-visible paths depend on the Shift definition:

- Shift summary in `doctype/shift/shift.py` and `doctype/shift/shift.js`
- Shift aggregate production metrics in `doctype/shift/shift.py`
- running timeline payloads in `api_timeline.py`
- Stock Entry Shift defaults and planned-window validation in `overrides/stock_entry_hooks.py`
- reports under `report/`

## Design

### 1. Running-shift duration revision

Keep the change narrow:

- allow edits to `shift_duration` on `Running` Shifts
- keep other Running-shift fields locked
- allow the server to update dependent fields during the same save:
	- `planned_end_time`
	- `shift_end_date`
	- regenerated `planned_losses`

This keeps the mutable surface small and avoids introducing a separate extension DocType or revision log for a single-field operational change.

Trade-off:
- simple and local to Shift
- weaker audit history than a dedicated revision model

### 2. Planned loss regeneration model

Make planned-loss generation fully deterministic from:

- `shift_date`
- `planned_start_time`
- `shift_end_date`
- `planned_end_time`
- `shift_duration`

Rules:

- `Shift Start Up` remains start-relative if that is still required by operations
- `JH Activity` becomes a fixed absolute slot: `10:00:00` to `10:10:00`
- tea/lunch/dinner breaks continue to use fixed clock-based definitions
- only rows overlapping the current Shift window are generated

Example:

- Shift window `2026-03-25 22:00` to `2026-03-26 08:00`: no `JH Activity` row is generated because the fixed `10:00 AM - 10:10 AM` slot is outside the active Shift window

Impact:

- shortening or extending a Shift will add/remove fixed break rows based on window overlap
- planned-loss deductions become consistent across UI, reports, and validation

Trade-off:
- deterministic and easy to test
- changes current behavior for `JH Activity`, so tests and any expectations built around the relative rule must be updated

### 3. Recalculation model

Do not rewrite historical production facts. Recompute derived metrics from the updated Shift.

Recomputed immediately:

- Shift summary snapshot and loss metrics
- completeness banners
- aggregate production entry cards
- running timeline end boundary
- reports that use Shift duration or Shift planned losses

Not rewritten:

- submitted Stock Entry actual start/end
- submitted quantities and rejections
- submitted Stock Entry copied planned-window fields

Draft/new Stock Entries:

- use the revised Shift values on next validate/save via existing Shift-default application
- no hidden bulk update across linked draft Stock Entries

Trade-off:
- avoids cascading writes and preserves historical submitted documents
- a draft Stock Entry can temporarily show stale copied planned end until reopened or revalidated

### 4. Overlap and validation behavior

When a `Running` Shift duration changes, validation must still enforce:

- allowed duration values
- no overlap with another non-cancelled Shift in the same department and branch

The overlap check should run against the recomputed end boundary. If the extension creates a collision, save must fail with the normal overlap error and no partial recalculation should persist.

### 5. UI behavior

Shift form behavior:

- `shift_duration` stays editable in `Running`
- `planned_losses` grid remains read-only in `Running`
- after save, the page refreshes the summary, linked aggregates, and any duration-driven helper display

Recommended UI copy:

- communicate that changing duration recalculates planned end time and planned losses

Trade-off:
- clear user behavior with low UI complexity
- less discoverable than adding a dedicated “Extend Shift” action

## Report Impact Analysis

### Directly impacted reports

#### Production OEE Report

`report/production_oee_report/production_oee_report.py` explicitly reads:

- `Shift.shift_duration`
- Shift planned losses

So a Shift extension changes:

- `avl_time_hrs`
- `availability_pct`
- `running_time`
- `stroke_required`
- `oee`
- `oee_mult_pct`

The new fixed `JH Activity` slot also changes planned-loss deductions here.

#### Operator Daily SPM Report

`report/operator_daily_spm_report/operator_daily_spm_report.py` sums `Shift.shift_duration` into `working_hours`.

So a Shift extension changes:

- `working_hours`

It should not change:

- `production_time_hrs`
- `spm`

unless the underlying production facts change.

### Indirectly impacted reports

These reports do not directly read `shift_duration`, but must be regression-tested because they use Shift-linked Stock Entries and loss-time helpers:

- `report/operator_efficiency_report/operator_efficiency_report.py`
- `report/workstation_efficiency_report/workstation_efficiency_report.py`
- `report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py`

Expected behavior:

- existing submitted data remains unchanged
- report values only change if future entry validation or loss recording changes because of the revised Shift window

### Mostly filter-only reports

The following families use `custom_pea_shift` mostly as a filter or grouping key and are not expected to change numerically just because a Shift is extended:

- rejection/rework pareto reports
- rejection/rework trend reports
- rejection/rework ppm reports
- item/BOM hotspot reports
- operator/workstation reason matrix reports
- operator rejection/rework performance reports

They still need a light regression pass to ensure no code path incorrectly assumes an immutable shift duration.

## Concrete Change Points

### Shift domain

Files:

- `production_entry_app/production_entry_app/doctype/shift/shift.py`
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

Changes:

- relax Running-state locking only for duration-driven recalculation
- replace fixed-loss generation rules for `JH Activity`
- ensure duration changes invalidate Shift summary cache
- add tests for:
	- Running shift duration update
	- recalculated planned end
	- recalculated planned losses
	- fixed `JH Activity`
	- overlap rejection after extension

### Shift page

Files:

- `production_entry_app/production_entry_app/doctype/shift/shift.js`
- Playwright coverage for the Shift page

Changes:

- keep duration editable in `Running`
- keep planned-loss grid locked
- refresh summary/aggregate UI after save
- cover the end-to-end user flow in E2E

### Timeline

Files:

- `production_entry_app/production_entry_app/api_timeline.py`
- `production_entry_app/public/js/timeline_renderer.js`
- `production_entry_app/production_entry_app/test_api_timeline.py`

Changes:

- ensure timeline caches are invalidated on Shift duration changes
- verify rendering against the extended end boundary

### Stock Entry integration

Files:

- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- `production_entry_app/production_entry_app/api.py`
- related tests under `overrides/`
- API tests under `test_api.py`

Changes:

- no submitted-document rewrites
- verify new/draft Stock Entries pick up the revised planned end via `_apply_shift_defaults()`
- verify planned-window validation immediately respects the extended Shift
- verify user-facing API payloads that hydrate Stock Entry forms continue returning current Shift end details after extension

### Reports

Files:

- `report/production_oee_report/production_oee_report.py`
- `report/operator_daily_spm_report/operator_daily_spm_report.py`
- `report/test_reports.py`

Changes:

- add tests showing OEE availability changes after a Shift extension
- add tests showing operator daily working hours changes after a Shift extension
- add regression coverage for unaffected report families where needed

## Testing Strategy

Required verification:

- unit tests for planned-loss generation with fixed `JH Activity`
- unit tests for Running-shift duration update and overlap rejection
- unit tests for cross-midnight extension cases so fixed-loss overlap remains explicit
- API tests for updated timeline end boundary
- API tests for `get_shift_details_for_stock_entry()` against an extended Running shift
- report tests for:
	- OEE availability before/after extension
	- operator daily working hours before/after extension
- Playwright E2E:
	- start Shift
	- extend duration
	- save
	- verify planned end and Shift metrics update

## Risks

### Denominator drift in reports

Risk:
- reports that depend on `shift_duration` or planned losses will show different values after extension

Mitigation:
- make this behavior explicit in tests
- keep the rule consistent: current Shift definition controls Shift-derived denominators

### Unexpected overlap failures

Risk:
- extending a Running shift may collide with another shift and prevent save

Mitigation:
- reuse existing overlap validation against the recomputed end boundary
- test same-day and cross-midnight cases

### Draft Stock Entry stale display

Risk:
- linked drafts can temporarily show stale copied planned-end data until they are touched again

Mitigation:
- keep the source of truth on Shift
- refresh values on validate/save
- document the trade-off instead of introducing hidden bulk rewrites

## Recommendation

Implement a narrow Running-shift duration revision path on the Shift doc. Recompute all Shift-derived scheduling and metric denominators from the updated Shift, keep submitted Stock Entries immutable, and update the planned-loss model so `JH Activity` is always a fixed `10:00 AM - 10:10 AM` slot.
