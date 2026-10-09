# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
