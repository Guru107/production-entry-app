# Overall figure for every column of every Script Report

Research date: 2026-11-04. Scope: for each Script Report under `production_entry_app/production_entry_app/report/`, decide the correct "overall" operation for every column (one overall row over the filtered result, Unassigned buckets included, no per-day subtotals). Research only; nothing implemented, no tests run. Repo claims cite file:line; anything inferred rather than read is marked **(inferred)**.

Path shorthand: `R/` = `production_entry_app/production_entry_app/report/`; `RU` = `R/report_utils.py`. Every report `.py` is `R/<name>/<name>.py`.

## Sources opened

- Report code, JS filters, JSON for all report directories; `RU`; `R/test_reports.py` (totals-row test only, lines 4124-4457); `R/pending_rework/test_pending_rework.py` (header).
- `docs/adr/0006`, `0007`, `0009`; `CONTEXT.md`; `docs/report_formula_conventions.md`; `docs/report-formulas/*.md` (production-oee, pending-rework, daily-rej-rework-register, operator-efficiency, operator-daily-spm, rejection-pareto, daily-strokes-spm-monitor); `docs/research/oee-availability-and-performance.md`, `docs/research/rejection-rework-ppm-denominator.md` (existing ASQ / IATF 16949 / Nakajima findings, not re-fetched).
- Frappe v16 source in the local bench: `/root/workspace/bench16/apps/frappe/frappe/desk/query_report.py:812-889`, `public/js/frappe/views/reports/query_report.js:1191-1215, 1995-2010`.

Could not verify: ISO 22400-2 aggregation rules. The ISO OBP page returned HTTP 403 to WebFetch, and `oee-availability-and-performance.md` already records that clauses 5/6 and Annex B are paywalled. No external definition is cited here for "sum bases, then recompute"; that rule rests on ADR 0007 and on arithmetic (a ratio of sums is the only aggregate that equals the ratio of the pooled population). No secondary blog is cited.

## 1. Summary and legend

There are **21** report directories, not 20 (listed in section 2). Findings in one paragraph: Eight reports need no new bases (Daily Strokes SPM Monitor, Rejection/Rework PPM, Rejection/Rework Trend, the two Matrices; Die Tool needs one small numerator). The other 13 need a carried base: Production and Monthly OEE (three dropped bases), Operator/Workstation Efficiency (strokes, production minutes and a weighted-SPM base are aggregated but not carried), Operator Daily SPM (operator+shift pairs), Operator Rejection/Rework Performance (`Avg Actual SPM` is a mean of ratios; reason map not carried), Hotspots (entry set and reason map), Pareto (entry/shift sets), Pending Rework (tree rows, source-entry set), and the Daily Rej Rework Register (a four-level tree with its own subtotals; a naive column sum double-counts). Frappe's native `add_total_row` cannot be used: it sums Percent columns then divides by row count (`desk/query_report.py:859-863, 873-874`), i.e. it averages percentages. All 21 report JSONs have `"add_total_row": 0`; only Daily Strokes SPM Monitor appends its own total row (`daily_strokes_spm_monitor.py:186-212`).

| Code | Meaning |
|---|---|
| SUM | Add the column over data rows |
| RECOMPUTE | Add the named bases, then apply the row formula to the totals |
| WAVG | Weighted average; weight named (implemented as RECOMPUTE of weighted-sum / weight-sum) |
| COUNT | Count or distinct count; "DISTINCT" means union of sets, not a sum of row counts |
| MIN/MAX | Earliest / latest |
| LABEL | Text "Overall" (translatable) in the first column |
| BLANK | Left empty; reason given |
| [carry] | A base the row does not currently carry and the overall builder needs |

Rules used everywhere:

1. Build the overall row from unrounded accumulators, not by summing displayed rows. Most reports return unrounded `flt(x)` (no precision argument), but the Register rounds (`daily_rej_rework_register.py:175-254`).
2. Never SUM or average Percent/ratio columns; never SUM text.
3. A count is SUM only when a Stock Entry lands in exactly one row. Entry-to-row cardinality per report is stated in each section.
4. Chart reports: build the chart from data rows before appending the overall row, and keep the overall row out of the chart.

## 2. Reports

### 2.1 Production OEE Report (`production_oee_report`)

Row = Production Date x Workstation (including downtime-only rows and an "Unassigned" workstation), `production_oee_report.py:257-296`. Machine-hour semantics: if two workstations run in the same Shift, each row carries that Shift's full duration (`_get_group_availability_hours`, :570-580), so Avl. time summed over rows is workstation-hours, which is what Availability needs. One Stock Entry has one workstation, so strokes/quantities are additive.

| Column (label / fieldname) | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Day / `day` | Date | LABEL | "Overall" | Dimension |
| Workstation / `workstation` | Data | BLANK | n/a | Spans all workstations |
| Strokes Required / `stroke_required` | Float | RECOMPUTE | Σ running_time x STD SPM(overall) x 60 (`compute_oee_rate_fields`, :88) | Keeps the row invariant Productivity = Act/Std. Differs from Σ of displayed rows when row STD SPM differ (Open Q1) |
| 1st Shift Strokes / `first_shift_strokes` | Float | SUM | Σ | Additive; 1st+2nd may be < Total (other shift labels, :485-491) |
| 2nd Shift Strokes / `second_shift_strokes` | Float | SUM | Σ | Same |
| Total Strokes / `total_strokes` | Float | SUM | Σ | Additive |
| Rejection / `rejection` | Float | SUM | Σ quality_rejection (includes rework, Right-First-Time; :482-483) | Additive. Not the same meaning as "Rejection Qty" in other reports |
| STD SPM / `std_spm` | Float | WAVG | Σ standard_spm_weighted_sum / Σ production_mins_sum; weight = production minutes (ADR 0006) | Settled. Fallback when Σ production_mins_sum = 0 or Σ weighted = 0: Open Q2 |
| Act SPM / `act_spm` | Float | RECOMPUTE | Σ total_strokes / (Σ running_time x 60) | Plant-wide effective SPM; matches `compute_oee_rate_fields` :81 |
| Productivity (P) / `productivity_pct` | Percent | RECOMPUTE | Act SPM(overall) / STD SPM(overall) x 100 | Ratio of totals |
| Quality (Q) / `quality_pct` | Percent | RECOMPUTE | (Σ quality_total - Σ rejection) / Σ quality_total x 100 | Needs `quality_total` [carry] |
| Availability (A) / `availability_pct` | Percent | RECOMPUTE | Σ running_time / Σ avl_time_hrs x 100 | Ratio of totals |
| Avg. OEE / `oee_avg_pct` | Percent | RECOMPUTE | (A + Q + P) / 3 using the overall A, Q, P | Same function as rows |
| OEE % / `oee_mult_pct` | Percent | RECOMPUTE | A x Q x P / 10000 using the overall A, Q, P | Not Σ or mean of row OEE |
| Avl. time (hrs) / `avl_time_hrs` | Float | SUM | Σ | Equipment-hours (see above) |
| 1st/2nd Shift `<reason>` / `reason_<code>_1st|2nd` (dynamic, one pair per filter code) | Float | SUM | Σ merged-interval hours per group (:341-349) | Merge is within a (day, workstation) group; groups are disjoint equipment-time |
| Machine Downtime / `machine_downtime` | Float | SUM | Σ | Per-workstation uncovered hours (:757-780), disjoint across groups |
| Total Loss Time / `total_loss_time` | Float | SUM | Σ | Includes all reasons, not only selected columns (:263) |
| Running Time / `running_time` | Float | SUM | Σ of row values (each clamped at 0, :265) | Additive base for A and Act SPM |

Bases not on the row: `quality_total`, `production_mins_sum`, `standard_spm_weighted_sum` are stripped by `_public_row` (:45-49, 98-99, called at :57). `get_rows_with_rollup_bases` (:61-67) still returns them, so the overall row must be built before `_public_row` runs. `avl_time_hrs`, `running_time`, `total_strokes`, `rejection` are already on the row.

### 2.2 Monthly Production OEE Report (`monthly_production_oee_report`)

Row = Workstation for one month of Production Dates (`monthly_production_oee_report.py:84-101`). Same column set as 2.1 with `day` replaced by `month` (:48-57). Rows are already sums of daily bases; the overall sums the same bases across workstations. One workstation maps to one row, so no row overlaps another.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Month / `month` | Data | LABEL | "Overall" | Dimension |
| Workstation / `workstation` | Data | BLANK | n/a | Spans all |
| Strokes Required, Act SPM, Productivity, Quality, Availability, Avg. OEE, OEE % | | RECOMPUTE | Exactly as 2.1, via `compute_oee_rate_fields` | Month row already does this at workstation grain (:157-179); ADR 0007. Note month `stroke_required` is Σ running x month STD x 60, not Σ of daily `stroke_required`, so Σ-of-rows already differs from Strokes Required here |
| STD SPM / `std_spm` | Float | WAVG | Σ weighted_sum / Σ production_mins (all workstations) | ADR 0006/0007 |
| 1st/2nd Shift Strokes, Total Strokes, Rejection, Avl. time, Machine Downtime, Total Loss Time, Running Time | Float | SUM | Σ month rows | Additive |
| Reason pairs (dynamic) | Float | SUM | Σ | Additive |

Bases not on the row: `_finalize_month_row` (:166-179) emits no `quality_total`, `production_mins_sum`, `standard_spm_weighted_sum` (they sit in `agg`, :89-90, in `_SUM_FIELDS` :18-30). Keep them on the aggregates and sum across workstations. `fallback_std_spm` is first-wins per workstation (:93-95) and cannot be pooled (Open Q2). This overall row supersedes the "no cross-workstation totals row" sentence in ADR 0007 and `CONTEXT.md` (Monthly Production OEE Report entry).

### 2.3 Daily Strokes SPM Monitor (`daily_strokes_spm_monitor`)

Row = Production Date x (Operator unless filtered) x Operation (:110-112). Already has a totals row (`_build_totals_row`, :193-212; test at `test_reports.py:4416-4457`). Each Stock Entry has one operator and one operation, so rows are disjoint. Recommendation: keep as is, only align the label ("Total" at :202 vs "Overall") (Open Q10).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Date / `date` | Date | LABEL | "Overall" (currently "Total") | Dimension |
| Operator / `operator` (hidden when Operator filter set) | Data | BLANK | n/a | Spans all |
| Operation / `operation` | Link | BLANK | n/a | Spans all |
| Setup Time (Hrs.) / `setup_time_hrs`, Loss Time (Hrs.) / `loss_time_hrs`, Prod. Time (Hrs.) / `prod_time_hrs` | Float | SUM | Σ | Disjoint per entry |
| Total Strokes / `total_strokes` | Float | SUM | Σ | Additive |
| SPM / `spm` | Float | RECOMPUTE | Σ total_strokes / (Σ prod_time_hrs x 60) (:200) | Not the mean of row SPM; already correct |
| Rejection / `rejection` | Float | SUM | Σ non-rework breakup rejection (:99-103, 138-141) | Additive |
| Rework / `rework` | Float | SUM | Σ | Additive |

Bases not carried: none; all on the row.

### 2.4 Operator Daily SPM Report (`operator_daily_spm_report`)

Row = Production Date x Operator x Workstation x Operation (:124). Trap: `working_hours` is the sum of `shift_duration` of the Shifts in the row (:165); the same Shift appears in every row of an operator who ran two workstations/operations in it, and in rows of different operators in the same Shift.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Date / `date` | Date | LABEL | "Overall" | Dimension |
| Operator, Workstation, Operation | Link | BLANK | n/a | Span all |
| Working Hours / `working_hours` | Float | SUM over distinct (operator, shift) | Σ over distinct (operator, shift_name) of `shift_duration` | Σ of rows double-counts an operator's Shift once per workstation/operation row (Open Q3). "Unassigned" collapses to one operator per Shift (**inferred** limitation) |
| Setting Time (Hrs) / `setting_time_hrs`, Loss Time (Hrs) / `loss_time_hrs`, Production Time (Hrs) / `production_time_hrs` | Float | SUM | Σ | Disjoint per entry (:146-155) |
| Total Strokes / `total_strokes` | Float | SUM | Σ | Additive |
| SPM / `spm` | Float | RECOMPUTE | Σ total_strokes / (Σ production_time_hrs x 60) (:170) | Plant effective SPM |

Bases not carried: the (operator, shift) pairs. Rows hold `agg["shift_names"]` only inside the aggregate (:132, 165), so keep operator+shift_names through to the overall builder.

### 2.5 Operator Efficiency Report (`operator_efficiency_report`)

Row = Operator (incl. "Unassigned") via `build_efficiency_rows` (`RU:1274-1301`). One entry has one operator, so Entries/quantities are additive.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Operator / `operator` | Link | LABEL | "Overall" | Dimension |
| Entries / `entries` | Int | SUM | Σ | One entry, one operator |
| Good Qty / `good_qty`, Rejection Qty / `rejection_qty`, Rework Qty / `rework_qty`, Total Units / `total_units` | Float | SUM | Σ (`total_units` = good + rejection, `RU:1242`; linear) | Additive |
| Actual SPM / `actual_spm` | Float | RECOMPUTE | Σ total_strokes / Σ production_mins (`RU:1283`); if Σ mins = 0 fall back to Σ actual_spm_sum / Σ entries (`RU:1285-1286`) | Effective SPM [carry] |
| Standard SPM / `standard_spm` | Float | WAVG | Σ(std_spm x production_mins over entries with both > 0) / Σ production_mins over the same entries | Row today is first-positive-wins (`RU:1259-1260`), which ADR 0006 rejected for OEE; docs claim weighted (`docs/report-formulas/operator-efficiency-report.md:13-14`, which also says `actual_spm = total_units / duration`, whereas code uses strokes, `RU:1283`) (Open Q4) |
| Operator Efficiency % / `operator_efficiency_pct` | Percent | RECOMPUTE | Actual SPM(overall) / Standard SPM(overall) x 100 | Ratio of totals |

Bases not carried: `total_strokes`, `duration_mins` (this is production minutes, `RU:1245-1247`), `actual_spm_sum`, and a new `standard_spm_weighted_sum` / its weight; all but the last exist in the aggregate (`RU:1216-1229`) but `build_efficiency_rows` does not emit them.

### 2.6 Workstation Efficiency Report (`workstation_efficiency_report`)

Identical to 2.5 with Workstation as the dimension (one entry, one workstation; "Unassigned" included) and `workstation_efficiency_pct`. Same operations, same missing bases, same Open Q4. Both reports go through the same `RU:1232-1301` helpers, so the overall is implemented once.

### 2.7 Operator Rejection Performance (`operator_rejection_performance`)

Row = Operator. Entries/qty additive (:95-97). `Total Qty` = `fg_completed_qty`, else good + total rejected (:79-82).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Operator / `operator` | Data | LABEL | "Overall" | Dimension |
| Entries / `entries` | Int | SUM | Σ | One entry, one operator |
| Total Qty / `total_qty` | Float | SUM | Σ | Additive |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ | Additive |
| Rejection Rate % / `rejection_rate_pct` | Percent | RECOMPUTE | Σ rejection_qty / Σ total_qty x 100 | Ratio of totals |
| Top 3 Reasons / `top_3_reasons` | Data | RECOMPUTE | Merge all operators' `reason_totals` (sum per reason), take top 3 by qty then name, format as `reason (qty)` (:141-142) | Union of the maps, not a join of row texts. Needs `reason_totals` [carry] |
| Avg Actual SPM / `avg_actual_spm` | Float | RECOMPUTE | Pooled entry mean: Σ actual_spm_sum / Σ actual_spm_count (entries with SPM > 0, :98-101) | Row is a mean of entry ratios; the consistent pool is the entry-weighted mean. Preferred alternative: change row and overall to effective SPM (Open Q5) |

Bases not carried: `reason_totals` map, `actual_spm_sum`, `actual_spm_count` (in `agg_by_operator`, dropped at :143-152).

### 2.8 Operator Rework Performance (`operator_rework_performance`)

Twin of 2.7 (diff reviewed): `Rework Qty` = `custom_pea_rework_qty or breakup rework_qty` per entry, reasons from `is_rework = 1` breakup rows, `Rework Rate %` = Σ rework_qty / Σ total_qty. All operations as 2.7 (`rework_qty`, `rework_rate_pct`, `top_3_reasons`, `avg_actual_spm`). Same carried bases needed. Denominator is total produced (ADR 0009).

### 2.9 Rejection Pareto Report (`rejection_pareto_report`)

Row = Rejection Reason, sorted by qty with cumulative % (:80-98). Chart: bar + cumulative line (`_get_chart`, :103-125; `execute` builds it from `rows` at :17-19). Trap: an entry with several reasons appears in several rows, and the same Shift likewise.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Rank / `rank` | Int | BLANK | n/a | Position, meaningless |
| Rejection Reason / `rejection_reason` | Data | LABEL | "Overall" | Dimension |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ (= `total_rejection_qty`, :70) | Additive across reasons |
| Rejection % / `rejection_pct` | Percent | RECOMPUTE | Σ qty / total_rejection_qty x 100 = 100 | Shares sum to 100 by construction; show 100 or BLANK (Open Q11) |
| Cumulative % / `cumulative_pct` | Percent | BLANK | n/a | A running total; the last data row already reads 100 (:86-87) |
| Entries / `entries` | Int | COUNT DISTINCT | \|∪ entry_sets\| | Σ of row counts overcounts multi-reason entries; set at :72 [carry] |
| Shifts / `shifts` | Int | COUNT DISTINCT | \|∪ shift_sets\| | Same trap; entries without a Shift contribute nothing (:73-75) [carry] |

Chart: unaffected provided the overall row is appended after `_get_chart(rows)` or excluded from it; an "Overall" bar equal to the sum would dwarf the reason bars and put a 100% point on the cumulative line.

### 2.10 Rework Pareto Report (`rework_pareto_report`)

Twin of 2.9 with `rework_qty` / `rework_pct` from `is_rework = 1` breakup rows. Same operations, same set carries, same chart rule.

### 2.11 Rejection PPM Report (`rejection_ppm_report`)

Row = Production Date. An entry belongs to one Production Date (via its Shift), so Entries are additive across rows (:55-89). Chart: daily PPM bar (:113-129).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Date / `date` | Date | LABEL | "Overall" | Dimension |
| Entries / `entries` | Int | SUM | Σ | One entry, one date |
| Total Qty / `total_qty` | Float | SUM | Σ | Denominator, ADR 0009 |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ | Additive |
| PPM / `ppm` | Float | RECOMPUTE | Σ rejection_qty / Σ total_qty x 1,000,000 (:99) | Never mean of daily PPM |

Chart: keep the overall row out of the daily bar chart (it would be a bar for the whole period). Bases not carried: none.

### 2.12 Rework PPM Report (`rework_ppm_report`)

Twin of 2.11 with `rework_qty` (`custom_pea_rework_qty or breakup rework`). Columns Date, Entries, Total Qty, Rework Qty, PPM; same operations: SUM / SUM / SUM / RECOMPUTE Σ rework_qty / Σ total_qty x 1e6. Same chart rule. No missing bases.

### 2.13 Rejection Trend Report (`rejection_trend_report`)

Row = Period (Daily / Weekly / Monthly grain, :58-66). Periods are disjoint and an entry has one Production Date, so Entries are additive. Chart: bar + rate line (:127-149).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Period / `period` | Data | LABEL | "Overall" | Dimension |
| Entries / `entries` | Int | SUM | Σ | One entry, one period |
| Total Qty / `total_qty` | Float | SUM | Σ | Additive |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ | Additive |
| OK Qty / `ok_qty` | Float | SUM | Σ (= Σ total - Σ rejection; row value is unclamped, :111) | Linear, so SUM equals recompute |
| Rejection Rate % / `rejection_rate_pct` | Percent | RECOMPUTE | Σ rejection_qty / Σ total_qty x 100 | Ratio of totals |

Chart: exclude the overall row; the series is a time trend. Overall is independent of the time grain. Bases not carried: none.

### 2.14 Rework Trend Report (`rework_trend_report`)

Same as 2.13 but columns Period, Entries, Total Qty, Rework Qty, Non-Rework Rejection Qty, Rework Rate % (no OK Qty column). SUM, SUM, SUM, SUM, SUM, RECOMPUTE Σ rework_qty / Σ total_qty x 100 (ADR 0009). Chart rule as 2.13. Bases not carried: none.

### 2.15 Item BOM Rejection Hotspots (`item_bom_rejection_hotspots`)

Row = (Item Code, BOM) from `get_item_bom_quality_hotspot_rows` (`RU:949-1025`). A joint LH/RH or Joint Production entry yields one fact per output slot, so one Stock Entry can sit in several rows (`RU:917-930`, set at :995). Item "Unknown" rows are real data and stay in the totals.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Item Code / `item_code` | Link | LABEL | "Overall" | Dimension |
| BOM / `bom_no` | Link | BLANK | n/a | Spans all |
| Entries / `entries` | Int | COUNT DISTINCT | \|∪ row entry sets\| (`RU:995, 1017`) | Σ overcounts joint entries [carry the sets] |
| Total Qty / `total_qty` | Float | SUM | Σ | Additive (slot gross, `RU:925`) |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ | Additive |
| Rejection Rate % / `rejection_rate_pct` | Percent | RECOMPUTE | Σ rejection_qty / Σ total_qty x 100 (`RU:1020`) | Ratio of totals |
| Dominant Reason / `dominant_reason` | Data | RECOMPUTE | Merge every row's `reason_totals`, take argmax (ties by name), text `reason (qty)` (`RU:1009-1012`) | Dominant text is not additive [carry reason_totals] |

### 2.16 Item BOM Rework Hotspots (`item_bom_rework_hotspots`)

Same helper (`is_rework=True`, fields `rework_qty`, `rework_rate_pct`); diff vs 2.15 is labels only. Same operations, same two carries (entry set, reason map). One implementation serves both.

### 2.17 Workstation Rejection Reason Matrix (`workstation_rejection_reason_matrix`)

Row = Workstation; columns = top-N reasons by total qty (N 1-20, default 10; :117-120), so the column set is dynamic. An entry has one workstation, so Entries are additive across rows. Entries counts only entries with at least one qualifying breakup row (:112), not all matching entries.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Workstation / `workstation` | Data | LABEL | "Overall" | Dimension |
| Entries / `entries` | Int | SUM | Σ (:126) | One entry, one workstation |
| Total Rejection Qty / `total_rejection_qty` | Float | SUM | Σ (each row sums all of its reasons, including those outside the top N, :127) | Additive. Trap: it will not equal the sum of the visible reason columns when more than N reasons exist |
| `<reason>` / `reason_<slug>` (dynamic) | Float | SUM | Σ column | Additive; equals `reason_totals[reason]` |

Bases not carried: none.

### 2.18 Workstation Rework Reason Matrix (`workstation_rework_reason_matrix`)

Twin of 2.17 (`is_rework=True`, `total_rework_qty`). Same operations.

### 2.19 Die Tool Stroke and Maintenance Report (`die_tool_stroke_and_maintenance_report`)

Row = Die Tool Counter, "as of now"; the only filter is Die Tool Item (:91-93); no date or Workstation/Operator dimension. Overall is weaker here: the counters are cumulative since each tool's last reset (`last_reset_on`), not a flow. A `stroke_capacity` of 0 means "no limit set" (utilization 0 and never due, `utils/die_tool_counter.py:90-91`).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Die Tool Item / `die_tool_item` | Link | LABEL | "Overall" | Dimension |
| Current Stroke Count / `current_stroke_count` | Float | SUM | Σ | Strokes in the current cycle across tools (weak but additive) |
| Max Stroke Count / `stroke_capacity` | Float | SUM | Σ over tools with capacity > 0 | Excluding zero-capacity tools keeps Utilization honest |
| Utilization % / `utilization_pct` | Percent | RECOMPUTE | Σ current (capacity > 0 tools) / Σ capacity x 100 (`get_counter_health`) | Capacity-weighted, not the mean of utilizations. If it reads from the visible Current column, the two sums use different tool sets (**inferred**), so carry a separate numerator |
| Warning Threshold % / `warning_threshold_pct` | Percent | BLANK | n/a | Per-tool setting, not a measure |
| Maintenance Due / `maintenance_due` | Check | COUNT | Number of tools due | A Check column cannot be summed meaningfully; render as count |
| Last Maintenance Date / `last_maintenance_date` | Datetime | MIN/MAX | MAX | Latest |
| Maintenance Count / `maintenance_count` | Int | SUM | Σ | One log, one item; tools without a counter row are not shown (:135-142, 155) so the sum covers only listed tools |
| Last Reset On / `last_reset_on` | Datetime | MIN/MAX | MAX | Latest |
| Last Reset By / `last_reset_by` | Link | BLANK | n/a | Identity of one user; no overall meaning |

Bases not carried: capacity > 0 filtered current-stroke numerator (see Utilization).

### 2.20 Pending Rework (`pending_rework`)

Tree report: item summary rows (`indent` 0) plus one detail row per (source entry, reason, warehouse) (`indent` 1) (:221-249). No date filter; Item filter only; the pool is a running balance "as of now" (`rework.py:182-193`, `max(produced - consumed, 0)` per item). Overall is weaker: it sums quantities of different items and possibly different UOMs **(inferred)**. All sums below run over the summary rows only; including detail rows would double-count `flagged_rework_qty`.

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Item Code / `item_code` | Link | LABEL | "Overall" | Dimension |
| Rejection Reason / `rejection_reason` | Data | BLANK | n/a | Detail-row attribute |
| Flagged Rework Qty / `flagged_rework_qty` | Float | SUM | Σ summary rows (= Σ detail rows, :224) | Additive by item |
| Derived Pending Qty / `derived_pending_qty` | Float | SUM | Σ summary rows | Per-item pool (already clamped at 0) |
| Rejection Warehouse Balance / `rejection_warehouse_balance` | Float | SUM | Σ summary rows (`Bin.actual_qty`, :190-200) | Stock balance: valid to add across items, never across time |
| Pool - Warehouse / `pool_balance_difference` | Float | RECOMPUTE | Σ pending - Σ balance (equals Σ of row differences) | Net figure; offsetting items cancel (Open Q7) |
| Source Entries / `source_entry_count` | Int | COUNT DISTINCT | \|∪ source entries across items\| | One source entry can contribute to several items, so Σ overcounts [carry the set from `details`] |
| Contributing Production Entry / `source_entry` | Data | BLANK | n/a | Detail-row attribute |
| Rejection Warehouse / `rejection_warehouse` | Data | BLANK | n/a | Detail-row attribute |

### 2.21 Daily Rej Rework Register (`daily_rej_rework_register`)

Row types (:176-255): per day, (a) a bold day header, (b) a bold item row, (c) rejection-line rows (one per breakup line), (d) a bold day subtotal. Qty columns repeat across levels, so a column sum double-counts: `rejection_qty` is on both line rows and the day subtotal; `rework_qty` appears as declared on lines/subtotal and as actual same-day rework on item rows (`docs/report-formulas/daily-rej-rework-register.md`, "Row values"). Compute the overall from the day-level figures, not by scanning columns. Lines are only listed for days with at least one breakup line (:119-120, 160), so the denominator covers listed days only (Open Q6).

| Column | Type | Overall op | Formula / bases | Why |
|---|---|---|---|---|
| Production Date / `production_date` | Date | LABEL | "Overall" | Dimension |
| Total FG Qty for Day / `day_fg_qty` | Float | SUM | Σ distinct listed days' `day_totals` (:172, 181) | Day-level and unfiltered by item/reason; each day once |
| No. of Operators(working) / `operator_count` | Int | COUNT DISTINCT | \|∪ day operator sets\| (`_get_rework_by_day_item`, :486-491) | Sum of daily counts counts an operator once per day worked [carry sets] |
| Time(hrs.) / `rework_hours` | Float | SUM | Σ day-header hours (:489) | Do not Σ item rows: a rework entry with several items repeats its hours in each item (:553-554) |
| Defective Item Code, Rejection Reason, Rejection Stage / `rejection_stage` | | BLANK | n/a | Row-level attributes |
| Rejection Qty / `rejection_qty` | Float | SUM | Σ line `rejection_qty` (= Σ day subtotals, :183, 247) | Not Σ of the column |
| Rework Qty / `rework_qty` | Float | SUM | Σ declared line `rework_qty` (= Σ subtotals, :185, 248) | Matches the subtotal convention; actual same-day rework (item rows) has no column in an overall row (Open Q6) |
| Finished Goods Qty / `finished_goods_qty` | Float | BLANK | n/a | The existing subtotal leaves it blank because only items with lines are listed and it is item-attributed (:241-255; doc "subtotal ... `Finished Goods Qty` is not summed"); alternative in Open Q6 |
| Rej PPM / `rej_ppm` | Float | RECOMPUTE | Σ rejection_qty / Σ day_fg_qty x 1e6 (:249) | ADR 0009 total-produced denominator; never mean of daily PPM |
| Rework PPM / `rework_ppm` | Float | RECOMPUTE | Σ declared rework_qty / Σ day_fg_qty x 1e6 (:250) | Same |
| Responsibility Remark, Reinspection, Operator Name | Data | BLANK | n/a | Text lists on item rows (:217-219); a union list is not a measure. Count of distinct operators sits in `operator_count` |

Bases not carried: the day operator sets and day-level `day_fg`/`hours` live in local dicts (`day_totals`, `rework_by_day`) in `_get_rows`; the overall builder runs inside `_get_rows` to reuse them. Precision: use the unrounded values, not the `flt(.., precision)` row cells.

## 3. Cross-cutting findings

**Bases to add**

| Report | Carry (not on the row today) |
|---|---|
| Production OEE | `quality_total`, `production_mins_sum`, `standard_spm_weighted_sum` (kept until after the overall row, dropped by `_public_row`, :45-49, 98-99) |
| Monthly OEE | the same three, through `_finalize_month_row` (:166-179) and across workstations |
| Operator / Workstation Efficiency | `total_strokes`, production minutes, `actual_spm_sum`, entry count, new `standard_spm_weighted_sum` (`RU:1216-1301`) |
| Operator Daily SPM | (operator, shift) pairs for Working Hours |
| Operator Rejection / Rework Perf. | `reason_totals`, `actual_spm_sum`, `actual_spm_count` (or strokes + production minutes if Open Q5 is adopted) |
| Hotspots (both) | per-row entry set and `reason_totals` (`RU:993-999`) |
| Pareto (both) | `entry_sets`, `shift_sets` (:51-52) |
| Pending Rework | source-entry set across items |
| Register | day operator sets, day FG and hours (already local dicts) |
| Die Tool | numerator restricted to capacity > 0 tools |

**Duplication and shared-helper opportunities (`RU`)**

- The guarded ratio `flt(num / den * K) if den > 0 else 0` is hand-written in about ten places (trend, PPM, operator performance, `RU:1020`, `RU:1287`, Register, `compute_oee_rate_fields`). One `safe_ratio(num, den, scale=1)` helper removes it and makes the overall recompute use the same code as rows.
- `Top 3 Reasons` and `Dominant Reason` both build "sort `reason_totals` by (-qty, name)" and format `reason (qty)` (`RU:1009-1012`, operator performance :141-142). Extract `format_top_reasons(reason_totals, n)`; the overall merges the maps first.
- Every rejection/rework pair (pareto, PPM, trend, matrix, hotspots, operator performance) is a near-copy; `diff` shows only quantity source and labels differ. Overall logic belongs in a shared builder, or it will be written eleven times.
- `build_efficiency_rows` (`RU:1274`) is shared by two reports, so one overall helper there covers both. Operator Efficiency docs and code disagree on Actual/Standard SPM (see 2.5).
- Overall-row plumbing: a small `append_overall_row(rows, overall)` plus one label constant; Daily Strokes SPM Monitor's `_build_totals_row` is the only precedent.
- Do not use native `add_total_row`: it SUMs Percent/Float columns and divides Percent totals by row count (`desk/query_report.py:859-863, 873-874`). The client also strips the last row and computes DataTable totals itself (`query_report.js:1191-1194`, `1995-2008`). A server-appended dict row is an ordinary data row, so a user sort on any column will move it (**inferred**; same behaviour already applies to Daily Strokes SPM Monitor; verify in the browser).

**Non-additive traps found**

- Entry counts where one Stock Entry occupies several rows: Hotspots (per output slot), Pareto (per reason), Pending Rework (per item), Register (per breakup line). One entry, one row (SUM safe): Efficiency, Operator/Workstation performance, PPM, Trend, Matrix (one workstation each), Production/Monthly OEE.
- Non-additive "as of" or level data: Pending Rework pool and balance (net of items), Die Tool counters (cumulative since reset).
- Text/rank columns: Top 3 Reasons, Dominant Reason, Rank, Cumulative %, Responsibility, Reinspection.
- Working Hours (Operator Daily SPM) repeats a Shift across rows.
- "Rejection" is not one quantity across reports: Production OEE `rejection` includes rework (Right-First-Time), while Efficiency, Daily Strokes SPM Monitor, PPM and Trend `rejection_qty` exclude it. Each overall uses its own report's base.
- Register: four row levels with overlapping totals; see 2.21.
- Row-level rate is first-wins in Efficiency reports (`RU:1259-1260`) vs production-time-weighted in OEE (ADR 0006).

## 4. Open questions (maintainer decisions)

Each carries my recommended answer; none changes anything already settled in the brief.

1. **Strokes Required on the OEE overall.** Recompute (Σ running x overall STD x 60) or Σ of displayed rows? They differ when rows have different STD SPM. Recommend recompute, matching the monthly row (:157-179) and keeping Productivity = Act/Std; accept that the column footer will not equal Σ of the column.
2. **STD SPM fallback and fallback-only rows.** ADR 0006 averages only entries with positive SPM and production time. Rows whose STD SPM is the Workstation fallback (running time but no contributing entry) carry strokes and running time into Act SPM but not into the weighted STD, so overall Productivity is biased. When Σ production_mins_sum = 0 the overall has no rate. Recommend: overall STD = Σ weighted_sum / Σ production_mins (ADR 0006); when that is 0, use running-time-weighted mean of the row STD SPM (Σ stroke_required / (Σ running x 60)); when running time is 0 show 0. Alternative if the bias matters: always use the running-time-weighted mean of the row STD SPM.
3. **Operator Daily SPM Working Hours.** Σ rows or distinct (operator, shift)? Recommend distinct (operator, shift) summed once.
4. **Efficiency reports' Standard SPM.** Code is first-positive-wins (`RU:1259-1260`), docs say production-time-weighted. Recommend aligning rows to production-time-weighted (ADR 0006) in the same change, since the overall needs the weighted bases anyway, and correcting `docs/report-formulas/operator-efficiency-report.md`. Not requested but flagged as a stale doc.
5. **Operator Rejection/Rework "Avg Actual SPM".** Row is a mean of entry SPM. Recommend replacing both row and overall with effective SPM (Σ strokes / Σ production time) per the maintainer's own reasoning; if the row stays, the overall is the pooled entry mean.
6. **Register overall scope.** (a) Denominator is production on listed days only, which overstates PPM against the period PPM from the PPM reports; recommend keeping it so the overall reconciles with the subtotals. (b) Rework Qty overall is declared (subtotal basis); recommend that, and leave actual same-day rework without an overall. (c) Finished Goods Qty: recommend BLANK; the alternative is Σ of item rows, which covers only items that had lines.
7. **Pending Rework Pool - Warehouse.** Net sum hides offsetting items; recommend net SUM plus nothing else (do not add a mismatch-item count column). Is an overall on mixed-UOM item quantities wanted at all? Recommend yes, with Item Code = "Overall".
8. **Die Tool Report.** Recommend the minimal overall in 2.19 and no more; if the maintainer prefers no overall on non-flow, as-of reports (Die Tool, Pending Rework), skip them. Recommend keeping both for consistency.
9. **Operators in the Register.** Distinct operators for the whole range (recommended) or operator-days?
10. **Label and placement.** One shared translatable "Overall" label (Daily Strokes SPM Monitor uses "Total" and the tests filter on it, `test_reports.py:4124, 4233, 4279`): recommend renaming and updating those tests. Place it as the last row, bold like the Register (`bold: 1`).
11. **Pareto Rejection %.** Show 100 or BLANK on the overall row? Recommend 100 (trivially consistent), BLANK for Cumulative %.
12. **Report count.** Brief says 20 reports; 21 directories exist (this document covers all 21).
