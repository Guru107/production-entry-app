# Rejection Row `is_finished_item` Spike

Date: 2026-07-01

## Method

I ran a bounded spike on both benches using `bench execute` against a temporary helper in `/tmp/pea_rejection_spike.py`.

The helper built a direct Manufacture Stock Entry from BOM, patched the rejection-row append behavior in memory for the running process only, and attempted submit/cancel. The spike definition required the rejection row to keep `t_warehouse = rejected warehouse` and `is_finished_item = 0`.

## Bench 16

Site: `frappe16.localhost`

| Criterion | Result | Notes |
|---|---|---|
| 1. Validate + submit without ERPNext error | FAIL | `frappe.exceptions.ValidationError: Source warehouse is mandatory for row 3` |
| 2. SLEs match expected quantities | NOT REACHED | Submit failed |
| 3. `se.get_finished_item_row().item_code` returns real FG row | NOT REACHED | Submit failed |
| 4. Cancel fully reverses SLEs | NOT REACHED | Submit failed |

Stock Entry: not submitted

SLE summary: none, because submit did not complete.

## Bench 15

Site: `development.localhost`

| Criterion | Result | Notes |
|---|---|---|
| 1. Validate + submit without ERPNext error | FAIL | `frappe.exceptions.ValidationError: Source warehouse is mandatory for row 3` |
| 2. SLEs match expected quantities | NOT REACHED | Submit failed |
| 3. `se.get_finished_item_row().item_code` returns real FG row | NOT REACHED | Submit failed |
| 4. Cancel fully reverses SLEs | NOT REACHED | Submit failed |

Stock Entry: not submitted

SLE summary: none, because submit did not complete.

## Verdict

`KEEP_OVERRIDE`

The spike definition does not validate under the requested row shape on either bench, so the override must stay.

## Caveats

- I did not alter the app implementation.
- The bounded spike helper lived in `/tmp` and was not committed.
- Because submit failed on both benches, SLE and cancel behavior were not reachable under this exact spike shape.
