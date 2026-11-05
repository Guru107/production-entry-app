# Overall Row sums bases and recomputes ratios

Reports end with an Overall Row that summarises everything the filters match. Quantity and time columns are summed; rate and percentage columns (OEE, Availability, Quality, Productivity, SPM, PPM) are recomputed from the summed bases using the same formula as a data row, because summing or averaging row percentages gives a figure that means nothing. A column that cannot be combined meaningfully across rows (ranks, cumulative %, dominant reason, as-of balances) is left blank. This supersedes the "no cross-workstation totals row" sentence in ADR 0007.

The Overall Row is a bold, server-built last row, not Frappe's `add_total_row`: the native total sums Float and Percent columns and divides Percent totals by the row count, which is exactly the wrong operation for ratios. The Rejection Pareto, Rework Pareto and Pending Rework reports have none.

## Considered Options

- Native `add_total_row`. Rejected: sums or row-averages ratio columns and cannot recompute from bases.
- Average of row percentages. Rejected for the reasons in ADR 0007: unequal row weights distort the result.
- Sum bases, then recompute. Accepted: the overall reconciles with the underlying Stock Entry data and agrees with every row's own formula.

## Consequences

- Reports must carry the bases the ratios are built from (for example Production OEE's `quality_total`, `production_mins_sum` and `standard_spm_weighted_sum`) until the Overall Row is built.
- Operator Rejection and Rework Performance report effective SPM (total strokes over total production time), not a mean of per-entry SPM, in rows and overall.
- Entry counts where one Stock Entry occupies several rows (hotspots, Register) cannot be summed; the overall counts distinct entries or distinct days.
- A server-built row is an ordinary data row, so sorting a column can move it.

Per-column rules: `docs/research/overall-figures-per-report-column.md`.
