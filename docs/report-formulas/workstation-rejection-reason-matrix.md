# Workstation Rejection Reason Matrix

Source: `workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py`

Grouped by workstation.

- `workstation`
- `entries`: distinct Stock Entry count for workstation.
- `total_rejection_qty`: sum of all mapped reason quantities for workstation.
- Dynamic reason columns (`reason_<slug>`): rejection qty for that reason in workstation.

Dynamic columns generated for top N reasons (default 10, clamped 1..20) by global descending rejection qty.

