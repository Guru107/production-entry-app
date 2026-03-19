# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

-   v16 compatibility while maintaining v15 support
-   `production_entry_app.compat` module for version detection (`IS_V15`, `IS_V16_OR_GREATER`)
-   `frappe_in_test()` compatibility wrapper for deprecated `frappe.flags.in_test`
-   `has_permission_strict()` for v16-compatible permission checks
-   GitHub Actions CI/E2E workflows updated to test against both v15 and v16
