# Report Formula Docs

Per-report column formulas are split into individual files in this folder.

- `production-oee-report.md`
- `operator-efficiency-report.md`
- `workstation-efficiency-report.md`
- `daily-strokes-spm-monitor.md`
- `operator-daily-spm-report.md`
- `die-tool-stroke-and-maintenance-report.md`
- `rejection-pareto-report.md`
- `rework-pareto-report.md`
- `rejection-trend-report.md`
- `rework-trend-report.md`
- `rejection-ppm-report.md`
- `rework-ppm-report.md`
- `item-bom-rejection-hotspots.md`
- `item-bom-rework-hotspots.md`
- `workstation-rejection-reason-matrix.md`
- `workstation-rework-reason-matrix.md`
- `pending-rework.md`
- `daily-rej-rework-register.md`

Shared conventions used by these formulas are documented in:

- `../report_formula_conventions.md`

## Overall Row

Every report above except the Rejection Pareto, Rework Pareto and Pending Rework reports ends with an
Overall Row for everything its filters match (ADR 0010). Quantities and times are summed; ratios (SPM,
Availability, Quality, Productivity, OEE, PPM, rates, efficiency %) are recomputed from the summed bases
using the same formula as a data row; columns with no meaningful overall are blank. The per-column rules
are in `docs/research/overall-figures-per-report-column.md`. Operator Rejection and Rework Performance
report `Actual SPM` as total strokes divided by total production minutes.
