# Rejection and rework PPM use the industry-standard total-produced denominator

The legacy Excel register ("REWORK & REJECTION REPORT", e.g. `PRESS SHOP REJ REW PPM 01 Jan-24.xlsx`)
computes its two daily rates against different bases: **Rej PPM = rejection qty / total day
production** but **Rew PPM = rework qty / finished-good (OK) qty**. When the Daily Rej Rework
Register was built to replace it, issue #207 proposed copying both formulas exactly so QA could
reconcile cell-for-cell with the audited legacy book. That would have made the app reports as
internally inconsistent as the Excel: the Rew PPM denominator (OK qty) is not the industry
standard, inflates without bound (it reaches 1,000,000 when all good output was reworked, as on
the real 01-Jan-24), and is incomparable with the register's own Rej PPM and customer scorecards.

Primary-source research (`docs/research/rejection-rework-ppm-denominator.md`, 2026-10-30) settled
the question:

- ASQ defines PPM as nonconformities normalized to a population of one million — the population,
  not the good output. Ford's IATF 16949 customer-specific requirements (§3.24) define PPM the
  same way: actual nonconforming material over total produced / shipped.
- ASQ's first-pass-yield convention counts rework as a first-pass loss over total input, and IATF
  16949 §8.7.1.4 (carried in the GM and STELLANTIS CSRs) treats rework as a nonconformity
  *disposition* with re-verification obligations — not as a rate measured against good output. No
  primary source was found that computes a rework rate over OK/good qty.
- IATF 16949 §4.3.2 does oblige an organization to honour customer-specific requirements, but a
  legacy Excel formula is only binding in that sense once the deviation is documented and
  customer-agreed. No such agreement exists for the OK-qty denominator.

## Decision

All rejection and rework PPM / rate figures in app reports divide by the **total produced
quantity** for the reporting scope (per day, item, period):

- `Rej PPM = rejection qty / total produced qty * 1,000,000`
- `Rework PPM = rework_qty / total produced qty * 1,000,000` (register, PPM report)
- `rework_rate_pct = rework_qty / total produced qty * 100` (trend report)

"Total produced" keeps its existing cross-mode meaning: `fg_completed_qty` for normal Manufacture
entries (falling back to good + rejected from child rows), the slot gross sums for Joint LH/RH and
Joint Production entries. A zero denominator yields `0`, never an error.

No code change resulted: the Daily Rej Rework Register, Rework PPM Report, and Rework Trend Report
already compute exactly these formulas. This ADR records *why* they must not be changed to match
the legacy Excel.

## Considered Options

- **Copy the Excel exactly (original issue #207 spec).** Rejected: bakes a non-standard,
  unbounded, cross-incomparable denominator into every rework rate in the app with no documented
  customer requirement behind it.
- **Hybrid: legacy-parity Rew PPM in the audited register, standard denominator in the trend
  reports, pending customer sign-off.** Rejected for now: it still publishes the non-standard
  figure in an IATF-audited artifact, and the sign-off that would justify it does not exist. If
  the customer later mandates the legacy formula as a customer-specific requirement, this option
  can be revisited with the agreement on file.
- **Standard denominator everywhere (chosen).** Matches ASQ / IATF 16949 conventions, keeps Rej
  and Rew PPM mutually comparable and consistent with customer PPM scorecards, and reuses the
  denominator the reports already have.

## Consequences

- The Daily Rej Rework Register's Rew PPM will **not** match the legacy Excel's Rew PPM. That
  mismatch is deliberate and permanent unless a documented customer-specific requirement says
  otherwise. Reconciliation is a documented translation, not a formula change:
  `legacy Rew PPM = standard Rew PPM * (OK qty / total produced qty)`.
- Issue #207 is closed as not planned; the conventions document
  (`docs/report_formula_conventions.md`) carries the normative formula statement.
- The "Total Qty" / "Total FG Qty for Day" columns already display the exact denominator used, so
  every PPM row stays self-auditable.
