# Disposable Test Company Cleanup Design

## Summary

Replace prefix-based best-effort test cleanup with disposable company-root cleanup.

The system will keep dedicated test company documents in place, but wipe all company-owned
test data beneath them at the end of Python and Playwright test runs. This avoids orphaned
records such as Stock Entries referencing deleted Items, which can happen with the current
reserved-artifact sweep.

## Goals

- Ensure automated tests leave the instance clean after the full suite finishes.
- Prevent orphaned records caused by partial cleanup.
- Make cleanup deterministic and easy to reason about.
- Keep cleanup scoped to explicitly disposable test companies only.

## Non-Goals

- Do not delete or recreate the Company document itself.
- Do not broaden cleanup into shared non-test companies.
- Do not rely on prefix inference as the primary cleanup mechanism.

## Current Problem

Current cleanup mixes:

- reserved-prefix deletion for E2E artifacts
- benchmark cleanup by dataset key
- lightweight per-test cleanup for Python tests

This is not a closed ownership model. It can delete masters such as Items or Warehouses while
leaving transactional documents that still reference them. The observed `Stock Entry` cancel
failure is one example: a Material Receipt survived while its test Item was deleted.

## Proposed Model

Introduce dedicated disposable companies:

- one for Python test data
- one for E2E test data

All automated test bootstrap helpers must create data only inside one of these disposable
companies. End-of-suite cleanup wipes all company-owned data inside the disposable company
while preserving the Company document itself.

## Company Strategy

Recommended company roots:

- `_PEA Python Test Company`
- `_PEA E2E Test Company`

The exact names can be finalized during implementation, but they must be:

- explicit
- centrally defined
- treated as an allowlist for destructive cleanup

If cleanup is asked to target any company outside that allowlist, it must fail immediately.

## Data Ownership Rule

Every automated test helper that creates company-scoped data must do so under one disposable
company root.

This includes, at minimum:

- Warehouses
- Departments
- BOMs
- Items
- Shifts
- Stock Entries
- Downtime Entries
- Die Tool Counters
- Die Tool Maintenance Logs
- benchmark fixtures

Any helper that attempts to create test data in a non-disposable company should fail fast.

## Cleanup Strategy

### Per-test cleanup

Keep the current lightweight per-test cleanup for speed:

- rollback transient DB state where appropriate
- restore Manufacturing Settings snapshots
- remove reserved benchmark artifacts if needed

This remains useful for isolation during the run.

### End-of-suite cleanup

Add a company-root cleaner that wipes all test data beneath a disposable company after:

- Python suite completion
- Playwright suite completion

This becomes the authoritative cleanup pass.

## Company-Root Wipe Semantics

The wipe must preserve the Company document and rebuildable essentials, while deleting
company-owned test data in dependency-safe order.

High-level order:

1. Stop or complete active runtime docs
2. Cancel submitted transactional docs
3. Delete transactional docs
4. Delete dependent masters
5. Restore company-local defaults needed for the next run

The cleaner should prefer explicit cancellation and normal deletes before force deletes.
Force deletes are only for known cleanup-safe cases.

## Cleanup Phases

### Phase 1: Quiesce runtime state

- End Running Shifts in the disposable company
- Resolve active test runtime state that blocks cancellation

### Phase 2: Cancel submitted transactions

Cancel submitted documents scoped to the disposable company, such as:

- Stock Entry
- Downtime Entry, if submittable in the target environment
- Die Tool Maintenance Log
- BOM, where submission state applies

If a document cannot be cancelled because of referential corruption, log it and stop the wipe.
Silent continuation here would reintroduce orphan risks.

### Phase 3: Delete transactions and child rows

Delete now-cancelled or draft transactional records and dependent child rows.

### Phase 4: Delete company-owned masters

Delete company-owned master data created for tests, including:

- BOMs
- Items
- Warehouses
- Departments
- Workstations where test-owned
- Operators where test-owned
- Die Tool Counters

Deletion order must respect ERPNext dependencies.

### Phase 5: Restore local defaults

Re-seed only the minimum company-local defaults needed for the next test bootstrap.

This keeps startup predictable without requiring full Company recreation.

## Python Test Integration

`before_tests()` should:

- ensure the disposable Python company exists
- ensure required minimal defaults for that company exist

At suite end, an automatic cleanup hook should:

- wipe the disposable Python company contents
- restore the minimal post-clean state

Per-test cleanup remains installed for app test cases.

## E2E Integration

`bootstrap_e2e_context()` should always use the disposable E2E company.

Playwright global teardown should:

- call a whitelisted cleanup endpoint
- wipe the disposable E2E company contents
- restore the minimal post-clean state

The existing prefix sweep can be reduced or removed once company-root ownership is complete.

## Safety Guardrails

- Cleanup only runs for companies in a fixed disposable-company allowlist.
- Cleanup logs targeted company and document counts before deletion.
- Cleanup aborts on unexpected target company.
- Helpers fail if they try to create test data outside disposable companies.
- End-of-suite cleanup should not silently skip cancellation failures that would leave
  invalid references behind.

## Error Handling

Use fail-fast behavior for ownership violations and cleanup-target mistakes.

For cleanup execution:

- expected missing records can be skipped
- cancellation failures on core submitted records should stop the wipe and log the document
- partial cleanup should be treated as a failed test-run teardown, not success

## Testing Plan

### Unit tests

- company allowlist enforcement
- helper rejection for non-disposable companies
- cleanup ordering over mocked doctypes
- end-of-suite cleanup invocation for Python path
- E2E teardown endpoint invocation path

### Integration tests

- wiping a disposable company removes all seeded Items, Warehouses, BOMs, Shifts, and Stock Entries
- company document remains
- post-wipe bootstrap can recreate required test context cleanly
- no orphaned Stock Entry / Stock Ledger references remain after cleanup

### Regression tests

- Material Receipt or other non-Manufacture test records do not survive while their Items are deleted
- cleanup does not touch shared companies

## Trade-offs

### Preserving the Company document

Pros:

- avoids ERPNext company bootstrap complexity on every run
- reduces risk around accounting trees and default master creation
- keeps cleanup focused on app-owned and company-owned test data

Cons:

- requires explicit wipe ordering and minimal re-seed logic

### Dedicated disposable companies

Pros:

- strong ownership boundary
- simpler reasoning than prefix inference
- lower risk of corrupting shared development data

Cons:

- requires all test helpers to consistently route data through the disposable company

## Open Implementation Decisions

- final disposable company names
- exact hook mechanism for Python end-of-suite cleanup
- exact Playwright global teardown integration point
- final allowlist/config location

These are implementation details and do not change the design direction.
