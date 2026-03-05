# Item BOM Rejection Hotspots

Source: `item_bom_rejection_hotspots/item_bom_rejection_hotspots.py`

Grouped by `(FG item_code, bom_no)`.

- `item_code`: finished good item from first matching finished, non-rejection detail row.
- `bom_no`
- `entries`: distinct Stock Entry count in group.
- `total_qty`: sum of entry total qty.
- `rejection_qty`: sum of entry rejection qty.
- `rejection_rate_pct`: `(rejection_qty / total_qty) * 100` if `total_qty > 0` else `0`.
- `dominant_reason`: highest breakup reason qty in group, rendered as `"Reason (qty)"`.

Rows sorted by descending `rejection_qty`, then `item_code`, then `bom_no`.

