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

The model is two-layered:

- company-root cleanup for company-scoped and company-owned records
- explicit reserved cleanup for global doctypes and singletons that are not company-scoped

Company-root cleanup becomes the primary ownership boundary, but it does not replace cleanup
for truly global test artifacts.

## Company Strategy

Recommended company roots:

- `_PEA Python Test Company`
- `_PEA E2E Test Company`

The exact names can be finalized during implementation, but they must be:

- explicit
- centrally defined
- treated as an allowlist for destructive cleanup

If cleanup is asked to target any company outside that allowlist, it must fail immediately.

## Execution Model

This design requires enforced site-exclusive automated test execution.

Contract:

- only one automated test run may target a given site at a time
- Python and E2E suites on the same site are serialized, not concurrent
- local development runs must not overlap with CI runs against the same site/database

This is enforced, not assumed:

- the site-level test/cleanup lock is acquired before any test bootstrap that creates disposable
  or reserved test data
- the lock is held for the full run lifetime, from bootstrap through suite teardown
- destructive cleanup requires that same lock to still be held
- if the lock cannot be acquired, bootstrap/teardown fails immediately
- authoritative runners must not proceed without the lock

## Data Ownership Rule

Every automated test helper that creates company-scoped data must do so under one disposable
company root.

This includes, at minimum:

- Warehouses
- Departments
- BOMs
- Shifts
- Stock Entries
- Downtime Entries
- Employees
- Die Tool Counters
- Die Tool Maintenance Logs
- benchmark fixtures

Any helper that attempts to create test data in a non-disposable company should fail fast.

## Ownership Map

The cleanup design must use an explicit doctype-to-ownership rule map instead of generic
heuristics.

Primary company-root path:

- `Warehouse` -> `company`
- `Department` -> `company` when field exists
- `BOM` -> `company`
- `Shift` -> primary predicate: linked `Department.company` is the disposable company; fallback
  predicate: reserved shift naming prefix owned by the suite
- `Stock Entry` -> `company`
- `Downtime Entry` -> primary predicate: linked `employee.company` is the disposable company;
  fallback predicate: reserved test naming/foreign-key path owned by the suite
- `Employee` -> `company`
- `Die Tool Counter` -> `die_tool_item` matching the reserved test item allowlist

Reserved-global path:

- `Item` -> reserved test item code/prefix allowlist
- `Operator` -> reserved name allowlist
- `Workstation` -> reserved name allowlist
- `Die Tool Maintenance Log` -> `die_tool_item` matching the reserved test item allowlist
- `User` -> reserved email/name allowlist
- `Role` -> reserved role-name allowlist
- `Downtime Reason` -> reserved reason-name allowlist
- `Manufacturing Settings` -> snapshot/restore, never delete
- `Global Defaults` -> snapshot/restore, never delete

If a doctype cannot be matched by one of these authoritative ownership rules, teardown fails
verification and no success response is returned.

## Global Artifact Policy

Not all current test artifacts are company-scoped.

The following must remain on an explicit reserved-artifact cleanup path rather than being
treated as part of company-root deletion:

- `Manufacturing Settings`
- `Global Defaults`
- `User`
- `Role`
- `Downtime Reason`
- `Operator`
- `Workstation`
- `Item`

For these doctypes:

- tests must use dedicated reserved naming conventions
- teardown must clean them by reserved ownership rules
- company-root cleanup must not assume that deleting the company subtree is sufficient

This means the final cleanup system is intentionally hybrid:

- disposable-company cleanup for company-owned records
- reserved-prefix cleanup for global artifacts

That is stricter than the current design and avoids pretending that all test data is
company-bound when the schema does not support that.

### Item policy

`Item` is treated as a reserved global artifact, not a company-owned record.

That means:

- test Items must use reserved ownership markers
- company-root cleanup must not assume Item deletion is implied by company wipe
- Item cleanup must only run after all dependent transactional docs have been cancelled and deleted
- post-clean verification must confirm no surviving `Stock Entry Detail`, `BOM`, `Stock Ledger Entry`,
  or similar dependency still references the reserved test Item before the Item is deleted

This resolves the ownership contradiction directly: `Item` participates in test cleanup, but on
the explicit reserved-global path rather than the company-root path.

## Cleanup Strategy

### Per-test cleanup

Keep the current lightweight per-test cleanup for speed:

- rollback transient DB state where appropriate
- restore Manufacturing Settings snapshots
- remove reserved benchmark artifacts if needed

This remains useful for isolation during the run.

Per-test cleanup must continue to restore and clean global state, especially:

- `Manufacturing Settings` snapshots
- benchmark fixtures
- reserved global Python-test artifacts only

### End-of-suite cleanup

Add a company-root cleaner that wipes all test data beneath a disposable company after:

- Python suite completion
- Playwright suite completion

This becomes the authoritative cleanup pass.

The authoritative cleanup consists of:

- company-root wipe for the disposable company
- reserved global-artifact sweep for non-company doctypes

## Company-Root Wipe Semantics

The wipe must preserve the Company document and rebuildable essentials, while deleting
company-owned test data in dependency-safe order.

High-level order:

1. Quiesce active runtime docs
2. Cancel submitted transactional docs
3. Delete transactional docs
4. Delete dependent masters
5. Restore company-local defaults needed for the next run

The cleaner should prefer explicit cancellation and normal deletes before force deletes.
Force deletes are only for known cleanup-safe cases.

## Cleanup Phases

### Phase 1: Quiesce runtime state

- Move active runtime docs into a deletable state without completing business workflows
- Stop Running Shifts in the disposable company without creating new downstream business records

For `Shift`, this requires a cleanup-only quiesce path. Cleanup must not call normal
business transitions such as `end_shift()` if those can create or mutate additional
business records. The cleanup contract is:

- transition to a deletable status using a cleanup-specific bypass/helper, or
- directly set the minimal state needed for cancellation/deletion under cleanup guardrails

### Phase 2: Cancel submitted transactions

Cancel submitted documents scoped to the disposable company, such as:

- Stock Entry
- Downtime Entry, if submittable in the target environment
- BOM, where submission state applies

If a document cannot be cancelled because of referential corruption, log it and stop the wipe.
Silent continuation here would reintroduce orphan risks.

### Phase 3: Delete transactions and child rows

Delete now-cancelled or draft transactional records and dependent child rows.

### Phase 4: Delete company-owned masters

Delete company-owned master data created for tests, including:

- BOMs
- Warehouses
- Departments
- Employees
- Die Tool Counters

`Item`, `Operator`, and `Workstation` are not assumed to be company-owned in the current
schema. They stay on the reserved-artifact path unless the implementation first introduces
and enforces a stronger ownership model for them.

### Phase 4b: Delete reserved global artifacts

Delete reserved global artifacts only after all dependent transactional and company-owned docs
have been removed.

This includes:

- Items
- Operators
- Workstations
- Die Tool Counters
- Die Tool Maintenance Logs
- Users
- Roles
- Downtime Reasons

Deletion must be guarded by explicit reserved ownership checks, not company filters.

Deletion order must respect ERPNext dependencies.

For `Die Tool Maintenance Log`:

- submitted logs must be cancelled before deletion
- cleanup must respect any counter side effects of that cancellation
- `Die Tool Counter` deletion happens only after maintenance logs and dependent transactions are gone

### Phase 5: Restore local defaults

Re-seed only the minimum company-local defaults needed for the next test bootstrap.

This keeps startup predictable without requiring full Company recreation.

## Python Test Integration

`before_tests()` should:

- ensure the disposable Python company exists
- ensure required minimal defaults for that company exist

Current repo state only exposes `before_tests()` directly and uses a per-test
`FrappeTestCase.run()` wrapper for cleanup. The design therefore requires an explicit
suite-end trigger, not an unspecified future mechanism.

Required design direction:

- keep the existing per-test cleanup wrapper
- add one explicit Python suite-finalization entrypoint for company-root cleanup
- ensure the test runner or CI command invokes that suite-finalization step once after all
  Python tests finish

At suite end, that finalization step should:

- wipe the disposable Python company contents
- clean reserved global test artifacts
- restore the minimal post-clean state

Benchmarks are part of the Python-test path.

Their ownership contract is:

- benchmark transactional and company-scoped data belongs to the disposable Python company path
- benchmark global masters such as reserved benchmark Items stay on the reserved-global cleanup path
- the Python suite-end finalization step is authoritative for benchmark cleanup

Per-test cleanup remains installed for app test cases.

The suite-end trigger is not an implementation detail; it is a required contract of this
design.

Mandated invocation path:

- provide a single bench-executable cleanup command in
  `production_entry_app.production_entry_app.utils.test_cleanup`
- authoritative Python suite runners must invoke it exactly once after `bench run-tests`
- a test run is considered incomplete if that command does not run

## E2E Integration

`bootstrap_e2e_context()` should always use the disposable E2E company.

Playwright global teardown should:

- call a whitelisted cleanup endpoint
- wipe the disposable E2E company contents
- clean reserved global E2E artifacts
- restore the minimal post-clean state

The existing prefix sweep cannot be fully removed because permission tests create global
`User`, `Role`, and `Downtime Reason` records that are not owned by company root.

Playwright teardown must therefore:

- fail hard on cleanup endpoint failure
- not merely warn and continue
- report a non-OK cleanup response as teardown failure

Python per-test cleanup must not delete reserved E2E globals. Cross-suite ownership stays split:

- Python cleanup handles Python disposable company + Python reserved globals
- E2E cleanup handles E2E disposable company + E2E reserved globals

## Safety Guardrails

- Cleanup only runs for companies in a fixed disposable-company allowlist.
- Cleanup logs targeted company and document counts before deletion.
- Cleanup aborts on unexpected target company.
- Helpers fail if they try to create test data outside disposable companies.
- End-of-suite cleanup should not silently skip cancellation failures that would leave
  invalid references behind.
- Global doctypes may only be cleaned when they match explicit reserved ownership markers.

## Helper Migration Boundary

Current helper architecture is centered around shared bootstrap helpers and one implicit
`resolve_test_company()` flow used by Python tests, E2E, and benchmarks.

The design requires a deliberate migration boundary:

- shared bootstrap helpers become parameterized by target disposable company and test mode, or
- separate Python/E2E bootstrap wrappers call a common lower-level helper with explicit company
  input

Recommendation:

- keep one common low-level helper layer
- add explicit company-aware wrapper functions for Python and E2E paths

This avoids duplicating bootstrap logic while removing the current implicit-company behavior.

Benchmark helpers follow the Python wrapper path, not a third company model.

## Error Handling

Use fail-fast behavior for ownership violations and cleanup-target mistakes.

For cleanup execution:

- expected missing records can be skipped
- cancellation failures on core submitted records should stop the wipe and log the document
- partial cleanup should be treated as a failed test-run teardown, not success
- cleanup should run inside explicit transaction boundaries where possible, with rollback before
  advancing to destructive follow-up steps

### Phase commit model

The wipe must be idempotent and phase-bounded.

Required boundaries:

1. Discovery phase
   - gather targeted records by ownership map
   - no writes
2. Quiesce/cancel phase
   - cancel or quiesce submitted/runtime docs
   - rollback entire phase on unexpected failure
   - commit only if phase completes successfully
3. Delete phase
   - delete now-safe records in dependency order
   - rollback this phase on unexpected failure before commit
   - commit only if phase completes successfully
4. Verification phase
   - verify no surviving forbidden references remain
   - if verification fails, teardown is failed and no success response is returned

Retry behavior must assume partial prior success only at committed phase boundaries.

### Playwright teardown contract

The E2E cleanup endpoint must return a strict success/failure payload.

If cleanup does not fully succeed:

- the endpoint returns non-OK status
- Playwright global teardown throws
- the nightly/CI run fails visibly

Warning-only teardown is not acceptable for this design.

## Derived ERPNext Records

Submitted transactions create ERPNext-managed derived records such as:

- Stock Ledger Entry
- Bin mutations
- GL Entry, where applicable
- Serial/Batch bundle links

The design assumes these derived records should disappear through normal cancel/delete invariants,
not direct force-delete as a primary strategy.

That contract requires:

- cleanup cancels top-level submitted transactions first
- cleanup only deletes masters after those cancellations succeed
- post-clean verification explicitly checks that no derived records still reference reserved test
  Items, Warehouses, BOMs, or surviving voucher numbers

If derived references remain after normal cleanup, teardown fails hard instead of continuing.

## Testing Plan

### Unit tests

- company allowlist enforcement
- helper rejection for non-disposable companies
- cleanup ordering over mocked doctypes
- end-of-suite cleanup invocation for Python path
- E2E teardown endpoint invocation path

### Integration tests

- wiping a disposable company removes company-root records such as Warehouses, BOMs, Shifts,
  Stock Entries, and Employees
- company document remains
- post-wipe bootstrap can recreate required test context cleanly
- no orphaned Stock Entry / Stock Ledger references remain after cleanup
- reserved global artifacts are deleted only after dependent records are gone
- reserved test Items are removed by the reserved-global sweep, not implied company-root wipe

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
