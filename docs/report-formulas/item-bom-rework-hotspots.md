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

**Overall Row** (ADR 0010): `total_qty` and `rework_qty` are summed, `rework_rate_pct` is recomputed from those totals, `entries` is the
**union** of the entry sets (a joint LH/RH entry sits in several item rows, so summing row counts would overcount) and
`dominant_reason` comes from the merged reason map.

