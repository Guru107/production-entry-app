# Production Changeover Release Plan — Production Entry App

**Date:** 2026-10-05  
**Target:** Production `https://trikayacoatings.frappe.cloud/`  
**Reference site:** Staging `https://trikayastagimng.frappe.cloud/` (app already installed)  
**Method:** Read-only ERPNext REST `GET` + local fixture/source inspection  
**Constraint honored:** No write, update, submit, cancel, delete, migrate, or install calls were made against Production.

---

## 1. Executive verdict

Production does **not** have `production_entry_app` installed. A naive `bench get-app` / install / migrate will hit a hard DocType name collision on **`Downtime Reason`**, leave a parallel legacy Stock Entry time workflow running beside PEA, and risk UI/script conflicts on Stock Entry.

Staging is the working template: PEA v1.0.0 is installed, Downtime Reasons are code-identified (`00`–`33`), legacy Stock Entry time fields remain in place, and conflicting client scripts for actual/loss time are already disabled.

**Do not install as-is on Production.** Follow the phased plan below, dry-run on a Production clone or Staging parity check first.

---

## 2. Current site state (Production, 2026-10-05)

### 2.1 Platform

| Item | Value |
|------|--------|
| Host | `trikayacoatings.frappe.cloud` |
| Auth user (API) | `agent@trikayacoatings.com` |
| Frappe | `15.121.0` |
| ERPNext | `15.121.3` |
| `production_entry_app` | **Not installed** |
| Notable apps | `trikaya` `0.0.5`, `india_compliance`, `hrms`, `npd_project_module`, others |

Versions have moved since the April 2026 impact note (then Frappe/ERPNext ~15.105/15.106).

### 2.2 App DocTypes on Production

| DocType | Status |
|---------|--------|
| Shift, Loss Entry, Operator, Rejection Reason, Rejection Breakup | Missing |
| Die Tool Counter, Die Tool Maintenance Log | Missing |
| Production Entry Settings, Rework Type, Rework Operator | Missing |
| **Downtime Reason** | **Present as host custom DocType** (blocker) |

### 2.3 Host `Downtime Reason` (blocker)

Observed Production metadata:

- Module: `Manufacturing`
- `custom`: `1`
- Submittable: `1`
- Autoname: `field:downtime_issue`
- Fields: `downtime_issue` (Data), `amended_from`
- Records: **31**

App expectation (fixtures / DocType JSON):

- Module: `Production Entry App`
- Non-custom app DocType
- Autoname: `field:code`
- Fields: `code`, `description`, `is_active`
- Standard fixture set: codes `00`–`22`

Linked host usage:

- Child table **`Loss Time`** (`Manufacturing`, custom, istable) has `loss_type` → Link `Downtime Reason`
- Used from Stock Entry field `custom_loss_time_details`
- Native Downtime Entry still uses Select `stop_reason` (1 draft record only)

### 2.4 Custom fields — fixture vs Production

App ships **68** Custom Fields (`module = Production Entry App`).

| Check | Result |
|-------|--------|
| `custom_pea_*` on Production | **0** |
| Fixture fieldnames already present | **0 collisions** |
| Fixture Custom Field *names* already present | **0 collisions** |

So PEA fields are additive. The risk is **workflow duplication**, not fieldname overwrite (except host ownership rules below).

**Host fields that must stay host-owned (do not overwrite / do not ship as PEA fixtures):**

| Field | Production state | App stance |
|-------|------------------|------------|
| `Stock Entry.branch` | Link, insert after `dimension_col_break`, Property Setter `reqd=1` | Host-owned; app copies from Shift only if field exists |
| `Stock Entry Detail.branch` | Present + fetch/reqd property setters | Host-owned |
| `Stock Entry.custom_stock_entry_purpose` | Data, read_only | Production-owned metadata |
| `BOM.custom_operation` | Link → Operation; set on **all 2455** BOMs | Production-owned; required for Joint Production |

Prior April risk (`Stock Entry-branch` in PEA fixtures) is **already fixed in current fixtures** — branch is no longer shipped by the app.

### 2.5 Parallel legacy Stock Entry workflow (keep until cutover)

Production Stock Entry custom fields (non-PEA) already capture production time:

| Legacy field | Role |
|--------------|------|
| `custom_planned_start_date` / `custom_planned_end_date` | Planned window |
| `custom_actual_start_date` / `custom_actual_end_date` | Actual window |
| `custom_workstation` | Workstation |
| `custom_standard_spm` | Standard SPM (**Data**, not Float) |
| `custom_time_logs` (Table → Job Card Time Log) | Actual time rows |
| `custom_loss_time_details` (Table → Loss Time) | Loss rows linked to Downtime Reason |
| `custom_total_actual_time` / `custom_total_loss_time` | Totals |
| `custom_department`, `custom_updated_branch`, `custom_press_rate` | Other host UX |

**Data volume (Production):**

| Metric | Count |
|--------|------:|
| Stock Entry total | 68,480 |
| Submitted | 66,849 |
| Manufacture submitted | 35,429 |
| With `custom_workstation` set | 24,572 |
| With `custom_actual_start_date` set | 24,565 |
| With `branch` set | 68,273 |
| Workstation masters | 20 |
| Active submitted BOMs | 1,296 |
| Rejected warehouses (`is_rejected_warehouse=1`) | 3 |

PEA will add a parallel `custom_pea_*` set. Reports already alias some keys (`custom_pea_workstation` ↔ `custom_workstation`, etc.) for read compatibility — that is not a full historical migration.

### 2.6 Scripts and overrides

**Enabled Stock Entry client scripts (Production):**

| Script | Risk with PEA |
|--------|----------------|
| Actual & Loss Time Calculation | High — drives legacy time/loss tables |
| Stock Auto Time | Medium — Job Card Time Log math |
| BOM | Medium — filters `bom_no` by `custom_operation` / stock entry type |
| Branch Fetching Stock Entry | Keep — host branch sync to items |
| Stock Entry Type | Keep — department mapping for Assembly types |

**Server script:** `SE Branch Update` (enabled) — after save on submitted docs, can rewrite `Stock Entry.branch`, detail `branch`, and related GL branch from `custom_updated_branch`. Compatible with host branch ownership; can diverge from Shift-stamped branch after submit.

**App global override (will apply on install):**

```text
Stock Entry → ProductionEntryAppStockEntry
```

Confirm `trikaya` (and any other app) does not also override Stock Entry before Production install.

### 2.7 Fixture property setters to validate on host meta

| Property Setter | Note |
|-----------------|------|
| `Downtime Entry-stop_reason-hidden/reqd` | Safe — native field exists |
| `Stock Entry-use_multi_level_bom-default=0` | Safe |
| `Stock Entry-bom_info_section-collapsible=0` | Safe if section exists |
| `Stock Entry-section_break_7qsm-collapsible=0` | **Validate on clone** — fieldname may be site/version-specific |

### 2.8 Staging reference state (already converted)

| Item | Staging |
|------|---------|
| `production_entry_app` | Installed `1.0.0` |
| Downtime Reason | Module `Production Entry App`, autoname `field:code`, 34 reasons (`00`–`33`) |
| Shifts / Operators / Rejection Reasons | 7 / 26 / 10 |
| SE with `custom_pea_shift` | 136 (pilot volume) |
| SE still with legacy `custom_workstation` | 19,377 |
| Legacy time client scripts | **Disabled** (`Actual & Loss Time Calculation`, `Stock Auto Time`) |
| Host branch CF + `branch-reqd` | Still present (correct) |

**Staging Custom Field drift vs current repo fixtures:**

| Direction | Fields |
|-----------|--------|
| Missing vs fixtures | `Downtime Entry-custom_pea_downtime_reason` |
| Extra vs fixtures (obsolete — **not in current codebase**) | `Item-custom_pea_strokes_per_unit`, `Stock Entry-custom_pea_rework_actual_start`, `Stock Entry-custom_pea_rework_actual_end`, `Stock Entry-custom_pea_stock_entry_purpose`, `Stock Entry-custom_pea_total_rm_consumption` |

Treat current fixtures as source of truth for Production. Clean staging extras before using staging as the golden image.

---

## 3. What changed DocTypes need (inventory)

### 3.1 New app DocTypes (create on install)

- Shift, Loss Entry (child), Operator  
- Downtime Reason (**replace/convert host custom DocType**)  
- Rejection Reason, Rejection Breakup (child)  
- Die Tool Counter, Die Tool Maintenance Log  
- Production Entry Settings  
- Rework Type, Rework Operator (child)  
- Branch Warehouse Default (supporting)

### 3.2 Existing ERPNext DocTypes receiving PEA Custom Fields

| DocType | Fixture CF count | Notes |
|---------|-----------------:|-------|
| Stock Entry | 56 | Main surface; parallel to legacy time fields |
| Stock Entry Detail | 2 | Rejection + joint side markers |
| Stock Entry Type | 2 | Joint + Rework flags |
| Item | 2 | Die tool flags/capacity |
| Workstation | 3 | `custom_pea_standard_spm` + timeline HTML |
| Downtime Entry | 2 | Link to PEA Downtime Reason + Shift |
| Landed Cost Taxes and Charges | 1 | Rework cost marker |

### 3.3 Host DocTypes touched by behavior (no PEA CF required)

- Warehouse (`is_rejected_warehouse` already present; 3 rejection warehouses ready)
- BOM / Operation (`custom_operation` required for Joint)
- Branch, Company, Department
- Stock Entry Type list (many Manufacture operation-named types already exist; add Joint/Rework types via fixtures/settings)

---

## 4. Custom fields — remove vs migrate vs keep

### 4.1 Remove (or never create) on Production

| Target | Action |
|--------|--------|
| Obsolete staging-only PEA fields listed in §2.8 | Do **not** create on Production; delete on Staging during cleanup |
| Any future PEA fixture that redefines `Stock Entry.branch` | Must stay absent (already true in current fixtures) |
| Host GST / e-Waybill / transporter Stock Entry fields | Never touch |
| Host `custom_department`, `custom_updated_branch`, `custom_press_rate` | Keep; not PEA-owned |

**Nothing PEA-owned exists on Production today to delete.**

### 4.2 Migrate (data / DocType), do not delete immediately

| From (host) | To (PEA) | When |
|-------------|----------|------|
| Custom DocType `Downtime Reason` (`downtime_issue`) | App DocType (`code`/`description`) | **Pre-install / install gate** |
| Known reason names → standard codes | See §5 dry-run map | With DocType conversion |
| Free-text leftover reasons | Custom codes `23`–`98` | Same conversion |
| `Loss Time.loss_type` links | Cascaded by `rename_doc` during conversion | Same window |
| Optional historical SE backfill: `custom_workstation` → `custom_pea_workstation`, actual/planned datetimes → `custom_pea_*` | Only if reports must include pre-PEA entries as Shift-based | Post go-live, optional batch |

### 4.3 Keep forever (host-owned)

- `Stock Entry.branch` / detail `branch` + property setters + Branch Fetching / SE Branch Update  
- `BOM.custom_operation`  
- `Stock Entry.custom_stock_entry_purpose`  
- Legacy time fields until business signs off dual-run end; then hide via Property Setter / Client Script disable, preferably **not** hard-delete (preserves 24k+ historical rows)

### 4.4 Parallel fields (intentional duplication during dual-run)

| Legacy | PEA |
|--------|-----|
| `custom_workstation` | `custom_pea_workstation` |
| `custom_planned_*` / `custom_actual_*` | `custom_pea_planned_*` / `custom_pea_actual_*` (+ date/time helper inputs) |
| `custom_standard_spm` (Data) | `custom_pea_standard_spm` (Float) on SE and Workstation |
| `custom_loss_time_details` / Loss Time | `custom_pea_unplanned_losses` / Loss Entry |
| Workstation `custom_standard_spm` | Workstation `custom_pea_standard_spm` |

Report aliases already cover workstation/shift/operator for some report paths; do not assume all PEA reports read legacy columns.

---

## 5. Downtime Reason conversion dry-run (Production names)

Using maps in `production_entry_app/utils/downtime_reason_conversion.py` against the 31 Production names:

**Merge/rename into standard/extra codes:**

| Legacy name | Code |
|-------------|------|
| Setup Time | 01 |
| No Operator | 03 |
| No Material | 04 |
| Maintenance, Machine Breakdown, Plant Maintenance | 05 |
| Power Off | 11 |
| 5 S ACTIVITY | 13 |
| TEA TIME | 14 |
| lunch | 19 |
| Trial | 22 |
| Tool Break, No Helper, Material Handling, TEA & TRAINING, tea time & 5s activity, 5 s activity,lunch & tea TIME, lunch & puwer cut | 00 |

**Likely custom codes `23+` (deterministic sort; confirm on clone):**  
`5 S ACTIVITY & VISKARMA PUJA`, cargo/material-short notes, Inventory, fixture/gun breakdowns, Shift Close Loss, manpower/mig welder short, etc.

**Install implication:** converting while the DocType is still the old custom schema is unsafe. Staging’s successful end state proves the sequence: replace/adopt PEA schema, seed `00`–`22`, then rename/merge legacy names (ADR 0005). Production must repeat that sequenced procedure, not only `bench migrate`.

---

## 6. Release plan (phased)

### Phase 0 — Decisions (human, before any Production write)

1. **Dual-run vs hard cutover** for Stock Entry time capture (recommend dual-run: PEA for Shift-based entries; legacy fields retained read-only for history).  
2. **Historical backfill:** none / workstation+times only / full loss-row migration. Default: **none**; new entries only.  
3. **Downtime Reason ownership:** PEA becomes system of record; host custom DocType retired (required).  
4. **Client script policy:** disable Actual & Loss Time Calculation + Stock Auto Time at cutover (mirror Staging).  
5. **Change window:** low Manufacture volume period; supervisors available for Shift pilot.

### Phase 1 — Repo / Staging hygiene (no Production writes)

1. Align Staging Custom Fields to current fixtures (add missing Downtime Entry reason field; remove obsolete extras in §2.8).  
2. Export/confirm fixtures: Custom Field, Property Setter, Downtime Reason, Rejection Reason, Stock Entry Type `Joint LH RH Production`, roles/perms.  
3. Confirm `trikaya` does not override Stock Entry class.  
4. Run full PEA test suite + Staging smoke: Shift start/end, Manufacture with Shift, Joint, Rework, OEE report, rejection warehouse.  
5. Document Staging Downtime Reason conversion runbook as the Production procedure (ADR 0005 + `convert_legacy_downtime_reasons`).

### Phase 2 — Production clone dry-run (mandatory)

On a Frappe Cloud backup/clone (or equivalent), **not** live Production:

1. Snapshot DB.  
2. Inventory `Downtime Reason` + count `Loss Time` rows by `loss_type`.  
3. Execute DocType adoption sequence (see Phase 3).  
4. `bench install-app production_entry_app` + `bench migrate`.  
5. Verify: 68 PEA Custom Fields; no change to `Stock Entry.branch` semantics; property setters applied or skipped safely.  
6. Run conversion; verify reason codes; spot-check Loss Time links.  
7. Disable legacy time client scripts; smoke Stock Entry Manufacture without Shift (must still save).  
8. Pilot: create Operator, Shift, one Manufacture with `custom_pea_shift`, one Downtime Entry with PEA reason.  
9. Record exact timings, failures, and SQL/manual steps for live run.

### Phase 3 — Production changeover sequence (writes only after explicit approval)

Order matters. Do not skip clone proof.

1. **Freeze / communicate**  
   - Pause new Downtime Reason master edits.  
   - Prefer short freeze on Manufacture entries that use loss-time tables during DocType swap.

2. **Backup**  
   - Full site backup; export Downtime Reason + Loss Time CSV.

3. **Adopt PEA `Downtime Reason` schema**  
   - Follow the Staging-proven procedure (custom DocType → app DocType with `code`/`description`/`is_active`).  
   - Preserve link integrity for `Loss Time.loss_type`.  
   - Install app / migrate so PEA DocTypes and fixtures land.

4. **Seed + convert reasons**  
   - `seed_standard_downtime_reasons` (also runs in `after_migrate`).  
   - Run `convert_legacy_downtime_reasons()` (or the same REST/ops procedure used on Staging).  
   - Verify 00–22 present; custom 23+ for site-specific leftovers; no orphan link names.

5. **Stock Entry Type / settings**  
   - Ensure Joint LH RH Production type and Rework type flags exist.  
   - Configure Production Entry Settings (rejection WH defaults per branch, rework type, access control as needed).  
   - Confirm Branch Warehouse Defaults for Nashik / Haridwar.

6. **Script cutover**  
   - Disable: `Actual & Loss Time Calculation`, `Stock Auto Time` (as on Staging).  
   - Keep: Branch Fetching, BOM query script, Stock Entry Type department script — unless smoke tests show PEA conflict.  
   - Leave `SE Branch Update` enabled unless Shift branch handoff conflicts in UAT.

7. **Pilot (limited users)**  
   - Create Operators; run 1–2 Shifts on one workstation.  
   - Submit Shift-based Manufacture; verify metrics, rejection breakup, die tool counter.  
   - Confirm non-PEA Material Transfer / Issue paths unaffected.  
   - Confirm OEE / utilization reports on pilot Shifts.

8. **Widen**  
   - Train supervisors; make Shift mandatory for Manufacture per policy.  
   - Optionally hide legacy Operation Details / Loss Time sections via Property Setter once adoption is solid.

9. **Post-go-live optional migration**  
   - Only if approved: batch-copy legacy workstation/actual times into `custom_pea_*` for reporting.  
   - Do **not** delete legacy columns in the same release.

### Phase 4 — Stabilization (1–2 weeks)

- Watch failed Stock Entry submits, branch mismatches, rejection warehouse errors.  
- Compare Manufacture counts vs pre-go-live baseline.  
- Keep rollback artifacts (backup, disabled-script list, reason export).

---

## 7. Rollback strategy

| Failure point | Rollback |
|---------------|----------|
| Before app install | Restore backup; no PEA artifacts |
| After install, before wide pilot | `bench uninstall-app production_entry_app` only if clone-tested; PEA `before_uninstall` deletes module Custom Fields/Property Setters — **does not** restore old Downtime Reason DocType |
| Downtime Reason conversion mistake | Restore from pre-conversion export/backup; conversion merges are hard to undo selectively |
| Script conflicts | Re-enable legacy client scripts; disable PEA use (access control / stop creating Shifts) |

**Implication:** Downtime Reason adoption is the least reversible step — prove it on a clone first.

---

## 8. Go / no-go checklist

- [ ] Clone dry-run succeeded end-to-end  
- [ ] Downtime Reason conversion verified; Loss Time links intact  
- [ ] `Stock Entry.branch` still required and not read-only-from-PEA  
- [ ] No Stock Entry class override clash with `trikaya`  
- [ ] Legacy time scripts disabled; PEA Shift Manufacture works  
- [ ] Non-Shift Stock Entries (Material Transfer, etc.) still submit  
- [ ] Rejection warehouses and Branch Warehouse Defaults configured  
- [ ] Joint / Rework Stock Entry Types configured if those flows are in scope for day 1  
- [ ] Staging CF drift cleaned so golden image matches fixtures  
- [ ] Explicit Production write approval obtained for each mutating step  

---

## 9. Sources

| Source | Role |
|--------|------|
| Production REST `GET` (this audit) | Live metadata, counts, scripts, samples |
| Staging REST `GET` (this audit) | Post-conversion reference state |
| `production_entry_app/fixtures/custom_field.json` (68 fields) | Desired PEA Custom Fields |
| `production_entry_app/fixtures/property_setter.json` | Desired property setters |
| `production_entry_app/fixtures/downtime_reason.json` | Standard codes 00–22 |
| `production_entry_app/hooks.py` | Overrides, doc_events, fixtures |
| `production_entry_app/lifecycle.py` | after_migrate seed/index behavior |
| `utils/downtime_reason_conversion.py` | Rename/merge maps |
| `docs/adr/0005-downtime-reasons-identified-by-standard-codes.md` | Conversion policy |
| `CONTEXT.md` (Branch Ownership Handoff, Production-Owned Joint Metadata) | Ownership rules |
| `docs/production-erpnext-readonly-impact-analysis.md` (2026-04-28) | Earlier findings; superseded where fixtures/versions differ |

---

## 10. Summary table — actions by artifact

| Artifact | Production now | Action |
|----------|----------------|--------|
| `production_entry_app` | Absent | Install after Downtime Reason plan |
| Host Downtime Reason | 31 custom records | Convert to PEA schema + codes |
| PEA Custom Fields | Absent | Add via fixtures (68) |
| Legacy SE time fields | Heavily used (~24.5k) | Keep; disable scripts at cutover; optional later hide |
| `Stock Entry.branch` | Required host field | Keep unchanged |
| `BOM.custom_operation` | Universal | Keep; needed for Joint |
| Obsolete staging PEA fields | N/A on prod | Never create; remove on staging |
| Client scripts (time) | Enabled | Disable at cutover (staging pattern) |
| Historical SE → `custom_pea_*` | N/A | Optional post go-live; not required for install |
