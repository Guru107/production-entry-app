# Shift Branch-Scoped Overlap Design

**Goal:** allow overlapping shifts across different departments or branches while requiring every Shift to belong to a branch.

## Decisions

- `Shift.branch` becomes required.
- Shift name stops embedding department and label and becomes day-sequence based:
  - `SHIFT-{shift_date}.{sequence}`
- Overlap validation is scoped to exact `department + branch`.
- Business label uniqueness is also scoped to exact `department + branch + shift_date`.
- Existing bootstrap and E2E helpers must always provide a branch when creating shifts.

## Trade-offs

- Sequence-based names are shorter and avoid name collisions across departments and branches, but names are less self-describing.
- Requiring branch improves operational clarity, but it increases setup/test fallout because every creation path must now provide one.
- Scoping overlap by `department + branch` matches the requested business rule, but it allows concurrent overlapping shifts across branches by design.
