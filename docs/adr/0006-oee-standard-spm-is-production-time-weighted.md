# OEE Standard SPM is production-time weighted

The Production OEE Report used the first positive Production Entry standard SPM on a
day/workstation row, so Productivity and Strokes Required ignored later rates and left
downtime-only rows at zero SPM even when the Workstation had a rate. OEE Standard SPM is
now the production-time-weighted average of entry rates that have both a positive SPM and
positive production time (same weighting as Shift summary). When no entry contributes, the
row uses the Workstation standard SPM. Strokes Required stays `OEE running time × OEE
Standard SPM × 60`, so downtime-only rows may show a Workstation SPM while Strokes
Required and OEE stay zero.

## Considered Options

- Keep first-positive entry SPM. Rejected because mixed-rate days bias Productivity toward
  whichever Stock Entry name sorts first.
- Always use Workstation SPM. Rejected because entry rates capture the job that actually ran.
- Weight by wall-clock duration or by OEE running time. Rejected in favour of production
  minutes already used by Shift summary.

## Consequences

Zero-production-time entries no longer set the row SPM; the Workstation rate is used
instead. Formula docs and OEE tests must assert the weighted value, not first-wins.
