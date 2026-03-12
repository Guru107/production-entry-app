# Ephemeral Test Site Cleanup Design

## Summary

Replace reusable-site cleanup with isolated ephemeral test sites.

Instead of trying to scrub a long-lived site back to a clean state after tests, each
authoritative Python or Playwright run will execute against its own disposable site and
database. End-of-run cleanup drops that entire site. This removes most of the ownership,
locking, and partial-cleanup complexity that comes from sharing one persistent test site.

## Goals

- Leave no test data behind after authoritative test runs.
- Eliminate orphaned records caused by partial object-by-object cleanup.
- Remove most cross-suite interference and locking complexity.
- Make cleanup deterministic by deleting the whole test site instead of inferring document
  ownership across a shared site.

## Non-Goals

- Do not preserve a reusable long-lived test site between authoritative runs.
- Do not implement a complex shared-site lock protocol unless a fallback is absolutely needed.
- Do not rely on prefix-based sweeping as the primary cleanup strategy.

## Core Decision

Authoritative automated runs should use isolated ephemeral sites, not a shared reusable site.

That means:

- each Python suite run gets a fresh site/database
- each Playwright suite run gets a fresh site/database
- teardown removes the entire site

This is the cleanup boundary, not individual doctypes.

## Execution Model

### Authoritative runs

Authoritative runs are:

- CI Python test jobs
- CI Playwright jobs
- any scripted local full-suite run intended to validate the branch end-to-end

These runs must:

1. create a fresh site
2. install required apps and test records
3. run the suite
4. drop the site in a `finally`/trap-style teardown path

### Non-authoritative local development

Developers may still use a long-lived local site for ad hoc debugging, manual testing, and
focused reproduction work.

That site is explicitly outside this cleanup guarantee.

If a developer chooses to run tests against a long-lived site, they accept that cleanup is
best-effort only. The “wipe clean on ending all tests” guarantee applies to authoritative
ephemeral-site runs.

## Site Strategy

Recommended pattern:

- Python site: per-run site name such as `pea-py-<run-id>.localhost`
- E2E site: per-run site name such as `pea-e2e-<run-id>.localhost`

Where `<run-id>` is unique per invocation.

The site name must also drive:

- database name
- Redis/cache namespace where relevant
- filesystem site directory

No two authoritative runs should reuse the same site name.

## Data Ownership Model

Ownership becomes simple:

- any data inside the ephemeral site belongs to that run
- cleanup deletes the entire site instead of deleting individual records by ownership inference

This removes the need to fully model ownership for:

- Stock Entries
- Shifts
- Items
- Warehouses
- Departments
- Users
- Roles
- Downtime Reasons
- Rejection Reasons
- counters, logs, and other derived records

They are all removed when the site is dropped.

## Why This Is Simpler

The current shared-site design forces the spec to answer hard and fragile questions:

- Which doctypes are company-owned vs global?
- What happens when links are already broken?
- How do we coordinate Python and E2E teardown on one site?
- How do we keep lock ownership across processes?
- How do we restore mutated singleton and per-user defaults?

Ephemeral sites avoid most of that. If the whole site is disposable, the cleanup problem is
mostly:

- create site correctly
- run tests
- reliably drop site even on failure

## Bootstrap Contract

Each authoritative runner must own site creation.

Required bootstrap steps:

1. create a fresh site with unique name
2. install `frappe`, `erpnext`, and `production_entry_app`
3. apply migrations / setup required metadata
4. for E2E sites, set site config `developer_mode=1` and `allow_e2e_tests=1`
5. seed required test bootstrap records
6. run tests against only that site

The current `before_tests()` logic remains useful, but it now targets the ephemeral site
created for the run rather than a shared persistent one.

## Teardown Contract

Each authoritative runner must own site deletion.

Required teardown behavior:

- teardown runs in a `finally`/trap-style path even when tests fail
- teardown drops the site directory and backing database
- teardown failure is itself treated as a failed run
- teardown logs the site name so failed cleanup can be manually recovered if needed

This is the authoritative cleanup guarantee.

## Failure Semantics

### Test failure

If tests fail, teardown still runs and should still remove the ephemeral site.

### Runner crash

If the runner crashes before teardown:

- the site name must be discoverable from logs or a run manifest
- a separate recovery command can list and delete stale ephemeral sites

This recovery path is much simpler than shared-site document cleanup because it still operates
at site granularity.

## Recovery Strategy

Add one recovery utility for stale ephemeral sites.

Responsibilities:

- list stale `pea-py-*` and `pea-e2e-*` sites
- show age / last modified time
- allow explicit deletion of stale sites

This is not the primary cleanup path. It is only a fallback for abnormal termination.

## Impact on Existing Cleanup Code

### Keep

- lightweight per-test rollback/snapshot cleanup for speed inside a single run
- benchmark cleanup helpers where they simplify test isolation inside the same ephemeral site
- focused helpers that make repeated tests in one run deterministic

### De-emphasize

- global reserved-artifact sweep as the authoritative end-of-run cleanup mechanism
- complex ownership inference for shared-site teardown
- long-lived shared test-company cleanup roots as the main solution

Shared-site cleanup helpers may still exist for local debugging, but they are no longer the
primary correctness mechanism.

## Python Test Integration

Authoritative Python test command structure should become:

1. create ephemeral site
2. run `before_tests()` / required setup against that site
3. run `bench --site <site> run-tests ...`
4. drop the site in a guaranteed teardown step

This should be wrapped in one script or command entrypoint so the teardown is not optional.

## Playwright Integration

Authoritative Playwright command structure should become:

1. create ephemeral site
2. install/setup app data for that site
3. set site config `developer_mode=1` and `allow_e2e_tests=1`
4. start an HTTP server that resolves requests to that exact site by hostname
5. expose that hostname as `PLAYWRIGHT_BASE_URL`
6. run Playwright against that site URL
7. drop the site in a guaranteed teardown step

The routing contract must be explicit:

- the ephemeral site must have a unique hostname such as `pea-e2e-<run-id>.localhost`
- bench/web-server configuration must resolve requests for that hostname to the matching site
- browser requests must hit that hostname directly rather than relying on a default site fallback
- if local DNS is not enough on its own, the runner must provide the required host mapping or
  host-header behavior as part of startup

Playwright global teardown should not be responsible for reconstructing ownership and sweeping
data inside a shared site. Its job becomes run-local cleanup only, while site deletion remains
the authoritative final cleanup.

## Security / Safety

Because teardown is destructive at site level:

- only site names matching the ephemeral naming contract may be dropped automatically
- recovery tooling must require explicit confirmation for stale-site deletion
- no automatic deletion should target non-ephemeral developer or production sites

## Testing Plan

### Unit tests

- ephemeral site name generation
- stale-site discovery logic
- safe filtering so only ephemeral sites are eligible for automatic drop

### Integration tests

- authoritative Python run creates and drops a temporary site
- authoritative Playwright run creates and drops a temporary site
- failed test run still triggers site teardown
- teardown failure marks the run failed

### Regression tests

- orphaned document issues on reusable sites no longer affect authoritative runs
- dropped ephemeral sites leave no residual app data in their database/site directory

## Trade-offs

### Advantages

- far simpler cleanup model
- avoids complex doctype ownership mapping
- avoids cross-suite interference on one shared site
- avoids most lock/token/heartbeat complexity
- strongest guarantee that no test data remains after the run

### Costs

- slower than reusing one warm site
- requires stronger runner/tooling around site creation and teardown
- local ad hoc runs against a persistent site still need separate expectations

## Recommendation

Use ephemeral sites for all authoritative Python and E2E runs.

Keep shared-site cleanup utilities only as local-development fallback tools, not as the main
correctness path.

This gives the cleanest path to the requirement: test-generated data should be wiped clean at
the end of all tests, without building a fragile shared-site cleanup engine.
