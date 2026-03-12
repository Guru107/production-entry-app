# Shift Department Display Name Naming — Design Spec

## Problem

Shift names currently derive the department segment from the linked Department document name. In ERPNext that name can include a company suffix such as `E2E Department - TC`, which leaks backend naming details into Shift names.

The desired behavior is simpler: use the Department's display label (`department_name`) for Shift naming, while keeping the Link field value unchanged.

## Decision

Use the linked Department document's `department_name` as the source for the Shift name segment.

Example:

- Linked Department docname: `E2E Department - TC`
- Department display label: `E2E Department`
- Shift name: `SHIFT-E2E-Department-2026-03-11.1`

This change applies to newly created Shift names only. Existing Shift records are not renamed.

## Recommended Approach

Resolve a naming label from the linked Department document at naming time and in all helper code that constructs expected Shift names.

Why this approach:

- Keeps Shift names stable even if Department docnames include company-specific suffixes
- Avoids brittle string stripping heuristics on docnames
- Keeps the Link field behavior unchanged and correct

## Alternatives Considered

### 1. Strip company suffix from Department docname

Rejected.

Trade-offs:

- Smaller code change
- Brittle if the docname format changes
- Can mis-handle legitimate department names containing similar suffix patterns

### 2. Add a separate stored naming field on Shift

Rejected.

Trade-offs:

- Explicit
- Adds unnecessary schema complexity for a simple derived value

## Implementation Shape

### Shift naming

- Add one shared helper in `doctype/shift/shift.py` that resolves the final naming source for a linked Department:
  - read `department_name`
  - if `department_name` is `NULL`, empty, or whitespace-only, fall back to the linked Department docname
  - return the resolved display string
- `Shift.autoname()` will call that shared helper and then sanitize the returned value
- Reuse the existing sanitization behavior from one shared helper; do not introduce parallel name-resolution or sanitization logic in API or test helpers

### Test and E2E helpers

- Update shared helpers that construct expected Shift names to call the same shared Department-name-resolution helper and the same shared sanitization helper used by `Shift.autoname()`
- Keep `ensure_department()` returning the actual Department docname for Link fields

### Cleanup behavior

- E2E cleanup should construct candidate Shift names using the same shared naming rule so bootstrap and teardown stay aligned for freshly bootstrapped data
- Explicit rule: use the bootstrap-returned Shift name as the primary cleanup key whenever that value is available
- Only fall back to predicted Shift names for flows that do not have the created Shift name available
- Predicted-name cleanup is best-effort only. If a Department display label changed after the Shift was created, cleanup must not assume the recomputed name will match the persisted Shift name

## Error Handling

- If the Department link is missing, keep the existing validation behavior
- If `department_name` is `NULL`, empty, or whitespace-only, fall back to the linked Department value rather than introducing a new hard failure path
- A successfully resolved non-blank `department_name` always wins over the Department docname

## Testing

- Add/adjust tests proving a Department docname like `E2E Department - TC` produces a Shift name based on `department_name`
- Keep regression coverage for E2E bootstrap/cleanup naming alignment
- Keep coverage proving Department lookup stays company-aware in bootstrap helpers

## Trade-off

This adds a Department metadata/value lookup when naming a Shift or when helper code derives an expected Shift name. The cost is small and local, and it keeps user-facing names independent of ERPNext's internal Department autoname behavior.

Another trade-off is reduced visual uniqueness across companies. Two Departments with different docnames but the same display label can now produce the same department segment in user-facing Shift names. That ambiguity is acceptable here because the numeric/date suffix still keeps document names unique, and the goal is simpler operator-facing names rather than globally descriptive department identifiers.
