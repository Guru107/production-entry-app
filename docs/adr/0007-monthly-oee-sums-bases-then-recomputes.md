# Monthly OEE sums bases then recomputes

A Monthly Production OEE Report row spans many Production Dates. Averaging daily OEE%
(or daily Availability / Quality / Productivity) mis-weights short and long days and breaks
the OEE product invariant. The month row sums the same bases the Production OEE Report
uses (available time, running time, strokes, quality quantities, rejection, Machine
Downtime, and OEE Loss Breakdown hours), keeps OEE Standard SPM production-time-weighted
across the month (ADR 0006), then recomputes Availability, Quality, Productivity, and OEE
from those totals. Downtime-only Production Dates are included; there is no
cross-workstation totals row.

## Considered Options

- Average daily OEE% (or daily A/Q/P). Rejected: unequal day lengths and zero-running-time
  downtime-only days distort the month score.
- Time-weighted average of daily OEE%. Rejected: still averages a product of ratios instead
  of recomputing from summed bases; industry practice (Vorne-style / ISO time elements)
  aggregates the underlying time and quantity elements first.
- Sum bases, then recompute. Accepted: matches daily row economics at month grain and
  stays consistent with production-time-weighted OEE Standard SPM.
