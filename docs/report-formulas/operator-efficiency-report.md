# Operator Efficiency Report

Source: `operator_efficiency_report/operator_efficiency_report.py`

- `operator`: group key (`custom_pea_operator`, fallback `"Unassigned"`).
- `entries`: count of Stock Entries in group.
- `good_qty`: finished-item quantity excluding rejection and scrap rows, aggregated per group.
- `rejection_qty`: aggregated entry rejection qty.
- `rework_qty`: aggregated entry rework qty.
- `total_units`: `good_qty + rejection_qty`.
- `actual_spm`: `total_units / duration_mins` (group level, production minutes denominator).
- `standard_spm`: `standard_units / duration_mins` where `standard_units = Σ(custom_pea_standard_spm * duration_mins)`.
- `operator_efficiency_pct`: `(actual_spm / standard_spm) * 100` if `standard_spm > 0` else `0`.
