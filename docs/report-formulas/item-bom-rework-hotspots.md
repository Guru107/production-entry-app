# Item BOM Rework Hotspots

Source: `item_bom_rework_hotspots/item_bom_rework_hotspots.py`

Grouped by `(FG item_code, bom_no)`.

- `item_code`
- `bom_no`
- `entries`
- `total_qty`
- `rework_qty`
- `rework_rate_pct`: `(rework_qty / total_qty) * 100` if `total_qty > 0` else `0`.
- `dominant_reason`: highest `is_rework=1` breakup reason qty as `"Reason (qty)"`.

Rows sorted by descending `rework_qty`, then `item_code`, then `bom_no`.

