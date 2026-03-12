# Shift Branch-Scoped Overlap Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** require `branch` on `Shift`, scope overlap and label uniqueness to `department + branch`, and switch Shift naming to per-day sequence numbers.

**Architecture:** update the `Shift` doctype validation and autoname rules in one place, then align test/bootstrap helpers and E2E setup so all Shift creation paths provide a branch. Keep the change narrow by reusing existing defaults/bootstrap helpers instead of introducing a new sequencing subsystem.

**Tech Stack:** Frappe, ERPNext, Python unittest, Playwright

---

## Chunk 1: Tests First

### Task 1: Update Shift tests for the new contract

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

- [ ] Add failing tests for branch-required validation.
- [ ] Add failing tests for sequence-based naming on the same date across different branches.
- [ ] Add failing tests proving overlap is blocked only for matching `department + branch`.
- [ ] Run the focused Shift test module and verify the new tests fail for the expected reason.

## Chunk 2: Model and Bootstrap

### Task 2: Implement branch-aware naming and validation

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.json`
- Modify: `production_entry_app/production_entry_app/utils/test_bootstrap.py`
- Modify: `production_entry_app/production_entry_app/utils/test_setup.py`
- Modify: `production_entry_app/production_entry_app/api.py`

- [ ] Make `branch` required in the doctype and validation path.
- [ ] Add branch defaulting only where bootstrap can safely provide one.
- [ ] Replace department/label-based autoname with date-sequence naming.
- [ ] Scope overlap and shift-label uniqueness by `department + branch`.
- [ ] Update bootstrap/E2E helpers to ensure a branch exists and is supplied on created shifts.

## Chunk 3: Verification

### Task 3: Verify Python and E2E flows

**Files:**
- Modify if needed: `tests/e2e/pages/shift-page.js`
- Modify if needed: `tests/e2e/specs/shift-validations.spec.js`

- [ ] Run focused Python tests for `Shift` and any touched helpers.
- [ ] Run the relevant Playwright spec(s) that create/save shifts.
- [ ] Fix any fallout from required-branch creation paths.
