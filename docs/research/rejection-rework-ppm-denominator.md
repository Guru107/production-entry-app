# Rejection (scrap) PPM and rework PPM: industry-standard denominators

Research date: 2026-10-30. Primary sources only (standards bodies, OEM/IATF first-party
publications, ASQ). No blog posts or vendor marketing used as the basis of any claim. Research
question raised by issue #207, which proposes copying the legacy Excel register's formula
(REW PPM = rework qty / finished-good (OK) qty × 1,000,000) into the app.

## Research question

For in-process manufacturing quality reporting (automotive press shop):

1. What is the industry-standard formula and denominator for rejection (scrap) PPM — total
   quantity produced, or OK/first-pass quantity?
2. What is the industry-standard formula and denominator for rework PPM / rework rate?
3. Does any mainstream standard or convention compute a "rework PPM" against good/OK output?
4. Is there quality-system precedent for matching a customer-audited legacy metric that deviates
   from the general standard?
5. Should the app (a) follow the Excel exactly as spec'd in #207, (b) follow the industry standard
   for both REJ and REW PPM (total produced), or (c) use a hybrid?

## Sources opened

- ASQ Quality Glossary, letter P — "Parts per million (PPM)" definition:
  <https://asq.org/quality-resources/quality-glossary/p> (accessed 2026-10-30; ASQ blocks direct
  fetches, content read via a text-rendering proxy).
- ASQ Quality Glossary, letter F — "First pass yield (FPY)" and "First time quality (FTQ)"
  definitions: <https://asq.org/quality-resources/quality-glossary/f> (same access method).
- ASQ Quality Resources — "What is Cost of Quality (COQ)?":
  <https://asq.org/quality-resources/cost-of-quality> (same access method).
- Ford Motor Company Customer Specific Requirements for IATF 16949:2016, Effective 15 June 2026,
  first-party PDF hosted by IATF Global Oversight:
  <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2026/06/Ford-IATF-CSR_Jun-2026-SCCAF_Final.pdf>
  (accessed 2026-10-30).
- General Motors Customer Specific Requirements for IATF 16949, Effective 30 October 2025,
  first-party PDF hosted by IATF Global Oversight:
  <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2025/10/IATF-16949-GM-Customer-Specific-Requirements-October-2025.pdf>
  (accessed 2026-10-30).
- STELLANTIS CSR for use with IATF 16949, v1 June 2025, first-party PDF hosted by IATF Global
  Oversight:
  <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2025/06/STELLANTIS-CSR-for-use-with-IATF16949-v1.pdf>
  (accessed 2026-10-30).
- IATF 16949:2016 Frequently Asked Questions, FAQ 31 revised and reissued June 2026, official IATF
  Global Oversight PDF:
  <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2026/06/IATF-16949-FAQs_June-2026.pdf>
  (accessed 2026-10-30).
- IATF Global Oversight — Customer Specific Requirements index page (lists every OEM's CSR):
  <https://www.iatfglobaloversight.org/oem-requirements/customer-specific-requirements/>
  (accessed 2026-10-30).
- AIAG Quality page (Core Tools; AIAG & VDA SPC Manual, product code SPCAV-1; APQP 3rd edition):
  <https://www.aiag.org/quality> (accessed 2026-10-30).
- ISO catalogue record for ISO 9000:2015 (shows withdrawal 2026-05-27, replaced by ISO 9000:2026):
  <https://www.iso.org/standard/45481.html> (accessed 2026-10-30).

## Findings

### 1. PPM is defined against a population, never against good output

ASQ Quality Glossary, "Parts per million (PPM)": *"A metric reporting the number of defects
normalized to a population of one million for ease of comparison."* The base of a PPM figure is
the whole population under consideration (parts produced, inspected, or shipped — depending on
scope), not the conforming remainder of it. (asq.org/quality-resources/quality-glossary/p,
accessed 2026-10-30.)

Ford's official CSR glossary (§3.24 "PPM (Part Per Million quality metrics)") defines PPM as
*"a method of stating the performance of a process in terms of actual nonconforming material"*
and is used "to prioritize corrective actions." Ford then operationalizes PPM as a monitored
customer metric: "Commodity PPM for both Production and Service" is one of the Q1
*zero-tolerance metrics*, and suppliers must "communicate Ford plant PPM (Parts Per Million) to
all organization plant team members" and provide the "Q1 Scoring Detail and Performance Metrics
Summary" to their IATF certification body. (Ford CSR for IATF 16949:2016, effective 15 June 2026,
§3.24, §9.1.2.1 and §10.2.3 context; accessed 2026-10-30.)

So the industry-standard shape is:

```text
PPM = (nonconforming qty / total population) × 1,000,000
```

where the population is the **total produced** for an in-process measure, or the **total
shipped/delivered** for a customer-facing measure. In both cases the denominator is the full
quantity that could have been nonconforming — not the OK quantity. The legacy Excel's REJ PPM
(rejection qty / total day production) matches this; its REW PPM (rework qty / finished-good qty)
does not.

### 2. First-pass conventions put rework in the numerator as a loss, on a total-input base

ASQ Quality Glossary, "First pass yield (FPY)": *"the percentage of units that completes a
process and meets quality guidelines without being scrapped, rerun, retested, returned or
diverted into an offline repair area. FPY is calculated by dividing the units entering the
process minus the defective units by the total number of units entering the process."*
(asq.org/quality-resources/quality-glossary/f, accessed 2026-10-30.)

Two consequences follow directly:

- The denominator of a first-pass quality rate is the **total units entering (produced)** — the
  same population logic as PPM.
- Reworked units are **not** "good": a unit that is "rerun … or diverted into an offline repair
  area" is a defective unit for first-pass purposes even if it later conforms. A rework rate on
  the same standard population base is therefore `rework qty / total produced`, and it measures
  the same first-pass failure class that FPY/FTQ measure.

The repo's own convention already encodes exactly this: `report_formula_conventions.md` counts
rework-flagged quantity as a quality loss at production time in the OEE Quality factor
(`Quality = (quality_total − quality_rejection) / quality_total`, with rework included in the
loss), and the Rework Trend Report today computes `rework_rate_pct = rework_qty / total_qty`
over the day's total produced. ASQ "First time quality (FTQ)" is defined the same way
("percentage of good parts at the beginning of a production run"), i.e. good-at-first-attempt
over the run.

### 3. Rework is standardized as a *nonconformity disposition*, not a separate rate — and no standard computes it over OK output

- ASQ Cost of Quality classifies both **scrap** ("defective product or material that cannot be
  repaired, used, or sold") and **rework or rectification** ("correction of defective material or
  errors") as **internal failure costs** — costs of defects found before delivery.
  (asq.org/quality-resources/cost-of-quality, accessed 2026-10-30.)
- IATF 16949:2016 contains a dedicated clause 8.7.1.4, **"Control of reworked product"** (its
  existence is corroborated by both the GM CSR and the STELLANTIS CSR, which are organized clause
  by clause against IATF 16949 and both carry an 8.7.1.4 entry). GM adds nothing there; STELLANTIS
  requires planned rework to be incorporated in the PFMEA and control plan, customer authorization
  for unplanned rework, and **re-verification of every reworked part** ("dimensional, fit, form,
  function, and/or reliability/durability"). (GM CSR Oct 2025 §8.7.1.4; STELLANTIS CSR v1 June
  2025 §8.7.1.4 / QRS 2.4.10.7.)
- The AIAG & VDA SPC Manual (product code SPCAV-1), the harmonized AIAG/VDA core tool for process
  performance metrics, is the current AIAG/VDA reference for stating process performance,
  including ppm-type figures; AIAG describes it as establishing "a harmonized approach to
  Statistical Process Control … to drive greater consistency throughout the global automotive
  supply chain." (aiag.org/quality, accessed 2026-10-30.) The manual itself is paid; its internal
  formulas were not read (see "Could not verify").

No primary source opened — ASQ, AIAG, IATF, Ford, GM, STELLANTIS — defines or uses a "rework
PPM" (or any nonconformance rate) whose denominator is the OK/good output. Every rate definition
encountered normalizes the nonconforming count by the **total population** (entering units,
produced units, shipped units, or inspected lot). This is an absence finding, not a positive
prohibition: the point is that the OK-quantity denominator in the legacy Excel is a local
convention, not anything the team's customer could point to as an industry-standard formula.

### 4. The audited-legacy-metric argument has real precedent — customer-specific requirements are first-class in IATF 16949

This is the strongest argument in #207's favor, and it is genuinely supported by primary
sources:

- IATF 16949:2016 §4.3.2: per the official IATF FAQ (June 2026), *"The organization is
  responsible for evaluating customer requirements, including customer-specific requirements, and
  including them in the scope of the organization's quality management system."*
  (IATF-16949-FAQs_June-2026.pdf, Q&A referencing IATF 16949 §4.3.2.)
- The IATF Global Oversight site maintains a canonical index of OEM Customer Specific
  Requirements (BMW, Ford, Geely, GM, Iveco, Mercedes-Benz, Renault, STELLANTIS, VW, Volvo),
  i.e. customer deviations from the generic standard are expected, published, and audited.
- STELLANTIS's CSR foreword states its QRS is "part of the contractual documents between
  STELLANTIS and its suppliers" and that the IATF portal documents exist so suppliers "can be
  audited as part of IATF 16949 certification rules … in a consistent way with the customer
  indicators." Its §4.3.2: *"All applicable QRS requirements are considered Customer-Specific
  Requirements … The supplier must integrate all the QRS requirements in its quality system and
  processes."*
- Ford's CSR makes customer PPM one of the Q1 zero-tolerance metrics reported to the IATF
  Oversight Office — a *customer-defined* PPM is enforced inside the IATF scheme itself.

So: matching a customer-audited metric even when it deviates from the general convention is
exactly how the automotive quality system works. **But** the precedent has a specific shape:
the deviation lives in a *customer-specific, documented, contractually agreed* requirement. An
informal legacy Excel is not automatically such a requirement — it becomes one only by customer
agreement/sign-off.

### 5. Comparison: legacy Excel vs industry standard

| Metric | Legacy Excel ("REWORK & REJECTION REPORT") | Industry standard (primary sources above) | App today (pre-#207) |
| --- | --- | --- | --- |
| REJ PPM | rejection qty / **total day production** × 1e6 | nonconforming / **total produced** (in-process) or total shipped (customer) × 1e6 — ASQ PPM glossary; Ford CSR §3.24 | rejection / total_qty — matches standard and Excel |
| REW PPM | rework qty / **finished-good (OK) qty** × 1e6 | no standard defines rework PPM over OK output; first-pass rates normalize by **total produced/entering** — ASQ FPY/FTQ; rework = internal failure cost (ASQ COQ); rework = controlled nonconformity (IATF 8.7.1.4) | rework / total_qty — matches standard |
| Rework rate % | (not present) | rework / total produced (same population base as FPY) | rework_rate_pct = rework / total_qty — matches standard |
| #207 proposes | REJ unchanged; **REW PPM and rework rate over OK qty in register, PPM report, and trend report** | — | — |

Note the Excel's internal inconsistency is not cosmetic: an OK-denominator rate can exceed
1,000,000 PPM (the #207 example: rework 1000 / OK 1000 → 1,000,000 PPM, and any rework qty
larger than OK qty gives >1e6), cannot be compared with the register's own REJ PPM or with any
customer PPM, and mathematically rewards high scrap days (more rejection → smaller OK
denominator → lower-looking rework rate).

## Recommendation

This is a recommendation, not a decision — the team weighs audit parity against standards
compliance.

**Recommended: (c) hybrid, tightened — Excel parity only where the audit comparison happens, the
standard denominator everywhere else, with the deviation recorded as a customer-specific
convention.**

- **Keep the industry-standard denominator (total produced) in the trend/PPM analytical
  reports** (`rework_ppm_report`, `rework_trend_report`). These are the app's forward-looking
  quality metrics; they are comparable with REJ PPM, with FPY/FTQ conventions, and with any
  customer scorecard. Issue #207's user stories 7–8 (changing the trend report and its rework
  rate to the OK-qty denominator) extend the legacy deviation into reports the customer does not
  audit against the Excel — that is where parity stops buying anything and standards-compliance
  starts costing something. Recommend pushing back on those two stories specifically.
- **For the Daily Rej Rework Register (the audited artifact), either** mirror the Excel's REW
  PPM denominator **with explicit customer sign-off documented** (the IATF CSR precedent: a
  customer-specific deviation is legitimate *when agreed and documented*), **or** keep the
  standard denominator there too and demonstrate reconciliation to the Excel with a
  documented translation factor. If the QA engineer's audit is row-for-row against the Excel,
  parity with sign-off is the lower-friction path and is defensible under the CSR precedent —
  provided it is labeled (e.g., a "Legacy Excel parity" note on that column) so a future reader
  does not mistake it for the standard formula.
- **Record the convention explicitly** in `docs/report_formula_conventions.md`: which reports
  use which denominator, why (customer-audited legacy register), and that the deviation is
  deliberate. This mirrors how IATF treats CSRs — a documented, intentional deviation with an
  owner.
- **Do not adopt the OK-qty denominator as the app's general "rework rate" definition** under
  any circumstances. No primary source supports it; it conflicts with the repo's existing
  first-pass-quality convention (OEE Quality, rework-trend) and makes rework rates
  non-comparable with rejection PPM and customer PPM figures.

Trade-off summary: pure (a) buys perfect row-for-row audit reconciliation but propagates a
non-standard formula into every rework metric in the app, doubling down on the Excel's internal
inconsistency. Pure (b) is maximally standards-compliant but forces the QA engineer to reconcile
the app against the Excel by hand at every audit until the customer agrees to retire the Excel.
The hybrid confines the legacy quirk to the one artifact it lives in, keeps the analytics
standard, and gives the team a documented basis for asking the customer to adopt (or formally
bless) one denominator.

## Could not verify

- Verbatim IATF 16949:2016 clause text for §4.3.2, §8.7.1.4, and §9.1.1.1 (iatf.org did not
  resolve at research time). Clause existence is corroborated by the GM and STELLANTIS CSRs
  (organized clause-by-clause against IATF 16949) and the official IATF FAQ quoting §4.3.2.
- The AIAG & VDA SPC Manual's (SPCAV-1) internal ppm formulas — the manual is a paid AIAG
  publication; only AIAG's product description was read.
- ISO 9000's vocabulary definitions for rework (ISO 9000:2015 was withdrawn 2026-05-27 and
  replaced by ISO 9000:2026 per the ISO catalogue; neither text was readable on the ISO Online
  Browsing Platform).
- VDA-specific quality-metric publications (e.g. VDA 6.x supporting documents) — paywalled; VDA's
  position is represented only through the joint AIAG & VDA SPC Manual.
- Ford Q1's exact Commodity PPM formula (numerator/denominator in Ford's scoring system) — the
  CSR references Q1 metrics but does not reproduce the Q1 formula table.

## Sources

1. ASQ Quality Glossary, letter P ("Parts per million (PPM)"),
   <https://asq.org/quality-resources/quality-glossary/p>, accessed 2026-10-30.
2. ASQ Quality Glossary, letter F ("First pass yield (FPY)", "First time quality (FTQ)"),
   <https://asq.org/quality-resources/quality-glossary/f>, accessed 2026-10-30.
3. ASQ, "What is Cost of Quality (COQ)?" (internal failure costs: scrap, rework/rectification),
   <https://asq.org/quality-resources/cost-of-quality>, accessed 2026-10-30.
4. Ford Motor Company, "Customer Specific Requirements for IATF 16949:2016" (effective
   15 June 2026), §3.24, §9.1.2.1, §10.2.3-area zero-tolerance metrics,
   <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2026/06/Ford-IATF-CSR_Jun-2026-SCCAF_Final.pdf>,
   accessed 2026-10-30.
5. General Motors, "Customer Specific Requirements for IATF 16949" (effective 30 October 2025),
   §8.7.1.4 and clause index,
   <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2025/10/IATF-16949-GM-Customer-Specific-Requirements-October-2025.pdf>,
   accessed 2026-10-30.
6. STELLANTIS, "CSR for use with IATF 16949" v1 (June 2025), Foreword, §4.3.2, §8.7.1.4 (QRS
   2.4.10.7),
   <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2025/06/STELLANTIS-CSR-for-use-with-IATF16949-v1.pdf>,
   accessed 2026-10-30.
7. IATF, "IATF 16949:2016 Frequently Asked Questions" (FAQ 31, June 2026), Q&A on §4.3.2 /
   §7.5.1.1,
   <https://www.iatfglobaloversight.org/wp/wp-content/uploads/2026/06/IATF-16949-FAQs_June-2026.pdf>,
   accessed 2026-10-30.
8. IATF Global Oversight, "Customer Specific Requirements" index,
   <https://www.iatfglobaloversight.org/oem-requirements/customer-specific-requirements/>,
   accessed 2026-10-30.
9. AIAG, Quality / Core Tools page (AIAG & VDA SPC Manual SPCAV-1; APQP 3rd edition),
   <https://www.aiag.org/quality>, accessed 2026-10-30.
10. ISO catalogue, ISO 9000:2015 record (withdrawn 2026-05-27; revised by ISO 9000:2026),
    <https://www.iso.org/standard/45481.html>, accessed 2026-10-30.
