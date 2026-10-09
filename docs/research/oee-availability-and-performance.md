# OEE availability and performance for a discrete press

Research date: 2026-09-28. Primary text only. Clause 5, clause 6, and Annex B of ISO 22400-2:2014 were not readable (paywall). SEMI E10 was not retrieved, so it is not used below.

## Sources opened

- ISO 22400-2:2014, informative sections on the ISO Online Browsing Platform: <https://www.iso.org/obp/ui/#iso:std:iso:22400:-2:ed-1:v1:en>. Catalogue record: <https://www.iso.org/standard/54497.html> (direct fetch blocked by Cloudflare). National bibliographic mirror, no formula text: <https://www.evs.ee/en/iso-22400-2-2014> (also lists ISO 22400-2:2014/Amd 1:2017; that amendment was not opened).
- Seiichi Nakajima, *Introduction to TPM: Total Productive Maintenance* (Productivity Press, 1988, ISBN 0-915299-23-2), pp. 22–28. OCR of the English edition: <https://archive.org/details/introduction-to-tpm-total-produtive-maintenance>.

Checked and not used as the ISO formula: Kang, Zhao, Li, and Horst, NIST-hosted PDF <https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=919754>, say they “modify and redefine” the ISO 22400-2:2014 elements. That is not a verbatim quotation.

## What ISO 22400-2:2014 shows in public

Scope: KPIs are “presented by means of their formula and corresponding elements.” Those formulas are in the normative sections. The OBP states: “Only informative sections of standards are publicly available.”

Public terms (clause 2):

- **planned time**: “planned duration of a specific time period.”
- **actual time**: “realized duration of a specific time period.” Note: actual time “may be less than, equal to, or greater than corresponding planned time.”

Public symbols (clause 3), names only:

| Symbol | Name in the standard |
| --- | --- |
| PBT | planned busy time |
| APT | actual production time |
| ADET | actual unit delay time |
| ADOT | actual unit downtime |
| AUBT | actual unit busy time |
| AUPT | actual unit processing time |
| AUST | actual unit setup time |
| PRI | planned run time per item |
| PQ | produced quantity |
| GQ | good quantity |
| OEE | overall equipment effectiveness |
| NEE | net overall equipment effectiveness index |
| LT | loading time |
| OPT | operating time |
| NOT | net operating time |

Annex B is titled “Alternative OEE calculation based on loss time model” (B.1 General, B.2 Time model for work units, B.3 KPIs). Its body did not load. LT, OPT, and NOT are the loss-time symbols; APT, ADET, and ADOT are separate elements in the same symbol list. The loss-time residual is the annex, not the only model in the standard.

**Not verified:** the clause 5 definitions of those elements, and the clause 6 equations for Availability, Effectiveness, Quality ratio, and OEE. No `Availability = APT / PBT` or `Effectiveness = PRI × PQ / APT` text was on the public page. Do not treat secondary restatements as the standard.

## Nakajima (verified)

Terms: **loading time**, **operation time** (also called operating time), **availability** (also called operating rate), **performance efficiency**, **rate of quality products**, **overall equipment effectiveness**.

Loading time is available time minus planned downtime (scheduled maintenance and planned management time such as morning meetings). Example: 480 minutes in the shift, 20 minutes planned downtime, loading time = 460 minutes.

Downtime subtracted from loading time is equipment stoppage from failures, setup, and adjustment. Idling and minor stoppages are speed losses, not this downtime.

Formulas, pp. 22–27 (table arithmetic on p. 28: operating time 400 / loading time 460 = 87%; performance efficiency 50%; OEE 0.87 × 0.50 × 0.98 = 42.6%):

```text
Availability = operation time / loading time
             = (loading time − downtime) / loading time

Performance efficiency = (processed amount × ideal cycle time) / operation time

Overall equipment effectiveness
    = Availability × performance efficiency × rate of quality products
```

The rate-of-quality-products factor is multiplied in; this edition does not spell that factor as an equation on these pages. It is given as 98% in the worked example.

## Decisions for the press

Planned busy time is the shift minus planned breaks. No production is recorded. One short unplanned stop is logged.

### A. Is the rest of planned busy time run time?

**ISO term:** actual production time (APT), not planned busy time (PBT). Delay and downtime have their own symbols (ADET, ADOT). Actual time is the realized duration of that period, not planned duration minus whatever was logged.

**Formula:** the Availability equation was not in the public text, so it is not quoted here.

**Choice the public text supports:** the unlogged remainder is not actual production time. APT is its own realized interval. A short logged stop does not make the rest of PBT into APT, and a blank production record does not either. Do not keep availability high by treating that remainder as run time.

**Nakajima, opposite residual:** operation time = loading time − downtime. After the logged stop, the rest of loading time is operation time, so availability stays high. Zero pieces hit performance efficiency, because the numerator is processed amount × ideal cycle time. He also says failure downtime of ten or twenty minutes left unrecorded makes operation time crude. That is a warning about missing logs, not a redefinition of operation time as “time a part was actually made.”

**Use for this press:** the ISO element model. Do not book the unlogged remainder as actual production time.

### B. When unplanned downtime shortens production time, which clock is performance on?

**Nakajima terms:** downtime shortens operation time; performance efficiency stays on that shorter operation time.

**Formula:**

```text
Performance efficiency = (processed amount × ideal cycle time) / operation time
```

Operation time already excludes downtime. The same stop is not also left in the performance denominator. If the remaining operation is at ideal cycle time, performance efficiency stays at 1 while availability falls. It can rise relative to a slower prior rate while availability falls. Speed loss and minor stops stay in this factor; they are not availability.

**ISO:** clause 6 Effectiveness was not visible. The public symbol list keeps APT apart from ADOT and ADET, and puts the loss-time model in Annex B as an alternative. That is consistent with rating effectiveness on actual production time rather than on the pre-downtime planned clock. It is not a quotation of the Effectiveness equation.

**Use for this press:** performance / effectiveness on the shorter actual production (operating) time. Downtime moves availability. It does not stay in the performance denominator.

## Could not verify

- ISO 22400-2:2014 clauses 5 and 6, Annex A effect models, and the body of Annex B.
- ISO 22400-2:2014/Amd 1:2017.
- SEMI E10 equipment states. No SEMI text was opened, so idle versus unscheduled time is not decided from SEMI here.
- A verbatim ISO sentence for `Availability = APT / PBT` or `Effectiveness = PRI × PQ / APT`.
