# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
