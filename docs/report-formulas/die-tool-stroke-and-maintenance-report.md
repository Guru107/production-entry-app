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

