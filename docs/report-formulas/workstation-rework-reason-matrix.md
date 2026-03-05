# Workstation Rework Reason Matrix

Source: `workstation_rework_reason_matrix/workstation_rework_reason_matrix.py`

Same as rejection matrix, but breakup rows are filtered by `is_rework = 1`:

- `workstation`
- `entries`
- `total_rework_qty`
- Dynamic `reason_<slug>` columns for top N rework reasons.

