# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.1] - 2026-10-23

### Fixed

-   Opening a submitted Manufacture entry without a Die Tool Item no longer marks the form dirty: the BOM die-tool auto-fill now skips submitted/cancelled documents instead of setting an unsavable value on every load (e2e regression spec included)
-   Test host-parity helpers only clean up custom fields they created, so suite runs no longer delete production-replicated fields (e.g. `Stock Entry.custom_department`) from host benches
-   The clean-site cutover test no longer re-installs legacy time-capture fields that the app's installation removed, keeping post-cutover hosts clean
-   Test BOM helpers set the production-required `BOM.custom_operation` link, so suites pass on host-parity benches where that field is mandatory

## [1.3.0] - 2026-10-23

### Added

-   Manufacture entries with a single BOM require a **Die Tool Item**: auto-filled from the BOM when it names one, otherwise the user picks it and an empty field is rejected at validate; the field is marked required for all shift-based production entries (#163)

### Changed

-   Joint (multi-BOM) Stock Entries no longer require every BOM to share one Die Tool Item; entries submit with a user-chosen die tool when BOMs disagree. The default uses the common value when all BOMs match, otherwise the first BOM in line order (#163)
-   Joint Fetch Items and rejection breakup layout is declared in the form layout (`insert_after` chains) instead of runtime JS repositioning; on Manufacture entries the breakup section now renders after Operation Details (#164)
-   Migration patches carry existing sites to the final layout: joint Fetch Items/rejection section relocation and Manufacture press field reordering (#163, #164)

### Fixed

-   Die tool auto-fill preserves the operator's choice when BOMs disagree (generator exhaustion in `prescribed_die_tool_item`) (#163)
-   Manufacture die tool error escapes the BOM number for `frappe.bold` (#163)

## [1.2.0] - 2026-10-22

### Added

-   Joint Production **Joint Production Line** child table: two or more BOM lines per entry, each with its own gross quantity, rejection quantity, and per-line rejection breakup (#153)
-   Joint Production Fetch Items materializes source, good, rejection, and aggregated scrap rows for every line from one action (#153)
-   Report and Shift pipelines read N line-derived slots for Joint Production entries; BOM and finished-item filters match through line BOMs (#153, #157)

### Changed

-   **Operation** report filter uses resolved operation per Stock Entry (`get_entry_report_operation`): Manufacture matches **Stock Entry Type**; Joint Production matches **custom_pea_operation**. Affects Operator/Workstation Efficiency, Production OEE, item/BOM hotspot reports, and SPM reports (#161)
-   Report formula documentation describes Operation column grouping and filter resolution (`report_formula_conventions.md`, per-report formula files) (#161)
-   Joint Production is redefined for unused-on-site semantics: output composition is unconstrained (same or distinct finished items per line), with a duplicate-recipe guard instead of fixed two-BOM same-item pairing (#153)
-   Joint output side labels generalize to BOM 1…BOM N on good, rejection, and breakup rows (#153)
-   Shift per-BOM stroke and production-minute attribution applies the entry totals to each line's BOM; Shift item summary lists each line's finished item (#153)
-   Stale Joint Production drafts saved before the line table must re-fetch items before submit (#153)
-   Manufacture and Joint Production stroke counters credit **Die Tool Item** from the Stock Entry when set (previously Manufacture credited the finished-good item) (#153)
-   Multi-BOM production entries require a single Die Tool Item across all selected BOMs on save (#153)

### Fixed

-   Stock Entry Shift link search lists Running and Completed shifts newest-first so the current Running shift appears in the first page (#160)
-   **Operator Daily SPM Report** and **Daily Strokes SPM Monitor** populate Operation from **Stock Entry Type** on Manufacture entries (sites that use operation-named types without `custom_pea_operation`); Joint Production entries continue to use the Operation link field

## [1.1.1] - 2026-10-18

### Added

-   Production entry Die Tool Item is set from the BOM when the BOM already names one; a submitted BOM can still record its Die Tool Item (#147, #152)
-   How-to guide for making production entries

### Fixed

-   Joint LH/RH item and rejection-breakup checks compare quantities at the System Settings float precision (#145)
-   Rework quantities, hours, and pending balances use the system float precision; Rework cost and Rework Register cost use the system currency precision (#145)
-   Quantity and currency tolerance follows ERPNext: both sides are rounded with `flt`, and a difference is rejected only when it exceeds one full unit at that precision (#145)

### Changed

-   A shift-based Joint Production run is counted once while each slot's quantity is attributed to its BOM (#151)
-   Domain glossary distinguishes Joint Production from Joint LH/RH Production

## [1.1.0] - 2026-10-09

### Added

-   Joint LH/RH Production Stock Entry Type: one press event for a paired LH and RH BOM, with shared strokes, per-side quantity and rejection, shared-sheet consumption for Shearing, and independent inputs for other operations
-   Rework Type master and Rework Stock Entry Type, with labour time recorded on each Rework Operator row
-   Pending Rework pool, Rework Register, and Pending Rework report
-   Shift-based and stock-only Production Entries: time, loss, stroke, and Standard SPM capture apply only when a Shift is set
-   Completed Shifts accept a longer duration without reopening, regenerating planned losses and rejecting an overlapping Company, Branch, and Department window
-   Downtime Reasons identified by standard codes 00–22, with a one-time conversion of legacy reasons
-   Downtime Entry stop reason links to Downtime Reason; downtime outside planned losses and Loss Entries counts as Machine Downtime
-   Monthly Production OEE Report, one row per Workstation for a calendar month of Production Dates
-   Production OEE loss breakdown for the Downtime Reasons selected in the report filter
-   Operation on production reports without double-counting Joint output
-   Company and Branch warehouse defaults in Production Entry Settings
-   Uninstall removes app-owned Stock Entry Types, the `PEA User` and `PEA Read Only` roles, and their custom DocPerms, and keeps referenced records with a named warning (#144)

### Changed

-   A Shift-based BOM Manufacture entry sets Total Press Strokes from finished quantity
-   Stock Entry department is copied from the selected Shift
-   Rework cost is loaded through a native Additional Cost row and is not an editable Stock Entry field
-   Rework-flagged quantity counts as a quality loss when it is produced; Rework Operations are left out of OEE and utilization
-   Operational reports select entries by the Completed Shift's Production Date
-   OEE Standard SPM is the production-time-weighted average of entries that have both a positive SPM and production time
-   Joint BOM operating cost is applied through native Additional Costs when there is no Work Order

### Upgrade

-   Take a site backup, then run `bench migrate`. The migration adopts a host Downtime Reason DocType in place, converts legacy reasons to standard codes, and removes the legacy time, operator, and workstation custom fields from forms. Frappe can leave the old database columns in place until they are dropped manually.

## [1.0.1] - 2026-10-04

### Added

-   Operator DocType bulk import via standard Frappe import (#75)
-   Select permissions for `PEA User` and `PEA Read Only` across Production Entry App DocTypes (#77)
-   Explicit PEA Read Only report authorization boundary for all app query reports (#78)

### Fixed

-   Frappe row-level permissions enforced on Shift timelines, summaries, aggregates, and production reports (#78)
-   `PEA Read Only` limited to the 18 reports shipped by Production Entry App (#78)
-   PEA User dependency read access for Stock Settings and related filter DocTypes (#78)
-   Stale `DocPerm` / `Custom DocPerm` rows cleaned during upgrades (#78)
-   Die-tool counter reads made side-effect-free; whitelisted Stock Entry payloads and linked-document permissions validated (#78)

### Changed

-   Inaccessible report Link columns render as plain text for `PEA Read Only` users (#78)
-   Shift summary caches partitioned by user; dynamic `frappe.bold` values HTML-escaped (#78)

### Infrastructure

-   Pinned `@playwright/test` to `1.58.2` for Node 18 CI compatibility (#76)

## [1.0.0] - 2026-07-19

### Added

-   v16 compatibility while maintaining v15 support
-   `production_entry_app.compat` module for version detection (`IS_V15`, `IS_V16_OR_GREATER`)
-   `frappe_in_test()` compatibility wrapper for deprecated `frappe.flags.in_test`
-   `has_permission_strict()` for v16-compatible permission checks
-   GitHub Actions CI/E2E workflows updated to test against both v15 and v16
-   Native Frappe role-permission coverage for `PEA User` and `PEA Read Only`
-   `PEA Read Only` read/select DocPerm fixtures for required standard ERPNext read surfaces
-   Read-only report access coverage across all Production Entry App query reports

### Changed

-   Production Entry App now relies on native Frappe Roles, DocPerms, and User Permissions for access control
-   Supported version matrix documents Frappe/ERPNext v15.110+ and v16.20 / v16.21+

### Fixed

-   `PEA Read Only` users can open Stock Entry read flows without write-capable ERPNext roles
-   `PEA Read Only` users can run Production Entry App reports that require Fiscal Year filters
