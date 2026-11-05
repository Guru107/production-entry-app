# Die Tool Stroke and Maintenance Report

Source: `die_tool_stroke_and_maintenance_report/die_tool_stroke_and_maintenance_report.py`

- `die_tool_item`: `Die Tool Counter.die_tool_item`.
- `current_stroke_count`: counter value.
- `stroke_capacity`: configured max.
- `warning_threshold_pct`: configured threshold, default 90.
- `utilization_pct`: from `get_counter_health(current_strokes, stroke_capacity, warning_threshold_pct)`.
- `maintenance_due`: from `get_counter_health(...)`.
- `last_maintenance_date`: max submitted maintenance date per item.
- `maintenance_count`: count of submitted maintenance logs per item.
- `last_reset_on`: counter metadata.
- `last_reset_by`: counter metadata.

**Overall Row** (ADR 0010): the counters are as-of-now levels, so this is a snapshot. `current_stroke_count`,
`stroke_capacity` and `maintenance_count` are summed; `utilization_pct` is capacity-weighted
(`Σ strokes of tools with a limit / Σ stroke_capacity`, blank when no tool has a limit — zero capacity means "no
limit set"); `maintenance_due` is the count of due tools; `last_maintenance_date` and `last_reset_on` are the latest.
Warning Threshold % and Last Reset By are blank.

