# Production ERPNext Rollout Design

Date: 2026-04-29
Status: Proposed

## Objective
Roll out Production Entry App to `trikayacoatings.frappe.cloud` without regressions or
surprises by rehearsing the production customization surface on local `bench15`, retiring
approved legacy Stock Entry customizations, protecting the existing `Stock Entry.branch` field,
and using an explicit irreversible production cutover runbook.

## Context
The production read-only impact analysis found that installing the app as-is is not low risk.
Production has existing Stock Entry custom fields, property setters, client scripts, server
scripts, and a custom `Downtime Reason` DocType that overlap with this app.

Important constraints:
- There is no production staging site.
- A local `bench15` site can be used as a production-schema replica.
- Production can tolerate a scheduled maintenance window with Stock Entry usage frozen.
- Production backup and rollback are not available.
- The cloud deployment is a one-shot release. All hardening must be complete before app
  submission.
- `PEA User` must not be assigned to production supervisors until install/update succeeds and
  non-PEA smoke checks pass.
- Old overlapping Stock Entry time/workflow fields, scripts, and reports are not required after
  PEA replaces the workflow.
- Historical data in old overlapping fields is not required.
- Existing `Stock Entry.branch` data and behavior must be preserved.

## Selected Approach
Use a controlled replacement rollout:

1. Export production metadata and recreate the impacted customization surface on a disposable
   local `bench15` site.
2. Rehearse legacy customization removal and PEA installation locally until the process is
   repeatable.
3. Harden the app and runbook case by case where local rehearsal or the impact analysis proves
   a conflict.
4. Execute production cutover only after the local replica passes all acceptance gates.

This is slower than a direct production install, but production has no rollback path. The local
replica becomes the required proving ground before any destructive production change.

## Alternatives Considered

### Direct Production Install With Manual Mitigation
Install the app during maintenance and fix conflicts as they appear.

Trade-offs:
- Pros: fastest setup.
- Cons: unacceptable risk with no rollback; known DocType and field conflicts could block or
  corrupt production metadata during the first real run.

### Pure Compatibility Rollout
Keep all existing production fields/scripts and make PEA coexist with them.

Trade-offs:
- Pros: avoids deleting legacy customizations.
- Cons: keeps duplicate UI fields and competing scripts, increasing operator confusion and
  behavioral drift.

### Full Workflow Refactor Before Rollout
Refactor PEA to reuse all existing production fields instead of `custom_pea_*` fields.

Trade-offs:
- Pros: potentially cleaner long-term integration with historical customizations.
- Cons: large scope, higher implementation risk, and unnecessary because old overlapping fields
  and reports are not required.

## Replacement Policy
Each overlapping production customization must be classified before production cutover:

- **Protect:** Keep unchanged. `Stock Entry.branch` is protected because its existing data and
  behavior are required.
- **Hide:** Hide old dummy-data custom fields during cutover and delete them only after one month
  of successful pilot use.
- **Disable:** Disable old scripts and old reports during cutover. Do not delete them in the
  initial cutover.
- **Keep:** Preserve because another required production process still depends on it.
- **Bridge temporarily:** Keep only if local rehearsal proves an immediate cutover would break a
  required process.

Likely removal candidates include older Stock Entry planning, workstation, time log, loss time,
and actual time fields and the client/server scripts that maintain them. They must still be
checked for dependencies in client scripts, server scripts, custom app code, reports, print
formats, and role workflows before removal.

The final deletion of hidden legacy fields is a separate post-pilot cleanup after at least one
month.

## Protected Branch Field
The existing production `Stock Entry.branch` field must remain intact:

- Preserve the field and existing values.
- Do not let PEA fixtures overwrite it to read-only or move it unexpectedly.
- Preserve production's required behavior unless a separately approved branch design changes it.
- Verify sample Stock Entries before and after rehearsal/cutover.

The app must remove its `Stock Entry-branch` fixture entirely. `Stock Entry.branch` is a
production prerequisite and may be created only by local test/dev setup when missing.

Preflight must hard-fail if `Stock Entry.branch` is missing or if critical metadata differs:
- fieldtype is not `Link`
- options is not `Branch`
- fieldname/name does not match the production field
- required behavior expected by production is missing
- read-only state is unexpectedly changed by this app

Cosmetic metadata differences, such as `insert_after`, should warn instead of hard-failing.

PEA-linked Stock Entries still set `branch` from the linked `Shift.branch` during validation.
Production's existing `SE Branch Update` server script must remain enabled because it has a
separate manual correction purpose. If branch correction is needed after submit, it is allowed.
`Shift.branch` may also be corrected after linked Stock Entries exist, but only through a
controlled, audited correction action for an authorized role; it must not be silently changed by
normal save hooks.

PEA operational reports should use `Shift.branch`; accounting/general ERPNext views may use the
final corrected `Stock Entry.branch`.

## Downtime Reason Conflict
Production already has a custom `Downtime Reason` DocType with a different schema from the app's
current `Downtime Reason` DocType. This is a hard install blocker.

Decision: keep production's existing `Downtime Reason` DocType and adapt the app to that schema.

Observed production schema:
- Module: `Manufacturing`
- Custom: `1`
- Submittable: `1`
- Autoname: `field:downtime_issue`
- Main field: `downtime_issue`

Required app changes:
- Remove the app-owned `Downtime Reason` DocType definition so install does not try to create or
  overwrite the production DocType.
- Update app code, fixtures, tests, links, and reports to treat `Downtime Reason` as the
  production-owned DocType.
- Replace references to app-only fields such as `downtime_reason_name` and `is_active` with the
  production schema, primarily `downtime_issue`.
- Replace `fixtures/downtime_reason.json` with idempotent seeding against the production-owned
  DocType. Use `downtime_issue` as the business key, check both `downtime_issue` and document
  name for uniqueness, and never overwrite existing production records.
- Match production's existing docstatus pattern for seeded reasons. If existing reasons are
  submitted, submit missing default reasons after insert; if draft reasons are the normal usable
  state, leave missing defaults as draft.
- Filter PEA downtime reason choices to submitted production reasons when production uses
  submitted records for normal use.
- Update permission/access assumptions because the DocType is production-owned and submittable,
  not an app-owned master.
- Add a preflight check that fails if the target `Downtime Reason` schema differs from the
  expected production-compatible schema.

Trade-off: adapting to production's DocType reduces operator confusion and avoids adding another
reason master, but it couples the app to a production customization. The local `bench15` rehearsal
must prove the app works against that exact schema before any production cutover.

## Preflight Tooling
Create a read-only preflight command or script before production cutover. It should compare the
target site against PEA assumptions and report:

- Existing DocTypes with names matching app DocTypes.
- Custom Field and Property Setter collisions.
- Active Client Scripts and Server Scripts on impacted DocTypes.
- Any existing app-level `Stock Entry` override conflict.
- References to removal-candidate fields in scripts, reports, print formats, and custom app code.
- `Stock Entry.branch` metadata and sample values.
- `Downtime Reason` schema and required default reason records.
- PEA field permission/permlevel setup.

The preflight must have a clear pass/fail output. If production preflight differs from the local
rehearsal immediately before cutover, stop before destructive changes.

A material difference means any difference that changes the approved cutover actions or risk:
- new or changed DocType, Custom Field, Property Setter, Client Script, or Server Script on an
  impacted DocType
- changed `Stock Entry.branch` metadata or sampled values
- new `Stock Entry` class override or hook conflict
- a removal-candidate field/script that appears, disappears, or has different dependencies than
  the local rehearsal
- missing reference data required for smoke tests

Production currently has no other `Stock Entry` class override. Keep PEA's existing global
`Stock Entry` override for rollout, but preflight must verify that no competing override appears
before cutover.

## Access And Field Permissions
PEA access has two role tiers:

- `PEA User`: read/write access for PEA workflows.
- `PEA Read Only`: read access for PEA forms, app visibility, reports, and monitoring/master
  context, with no create/write/submit permissions for PEA workflows.

`System Manager` remains an override. `PEA User` implies read access; users do not need both PEA
roles.

Update `Production Entry Settings` from one `required_role` to separate configurable defaults:
- `write_role = PEA User`
- `read_role = PEA Read Only`

Use native Frappe field permissions as the primary field access boundary:
- App-generated fields on standard DocTypes use a PEA permlevel.
- `PEA User` gets read/write at that permlevel.
- `PEA Read Only` gets read-only at that permlevel.
- Non-PEA users keep normal permlevel-0 access only.
- JS hiding remains UX-only, not the access boundary.

Define app-generated fields mechanically as Custom Fields with module `Production Entry App`,
excluding production-owned fields such as `Stock Entry.branch` and non-app-generated fields such
as `Warehouse.is_rejected_warehouse`.

Report visibility should use Frappe report roles/permissions for `PEA User` and
`PEA Read Only`; add custom report hiding only if local rehearsal proves native Frappe behavior is
insufficient.

## Stock Entry Activation Guard
Role access and document activation are separate:

- Role access controls who can see or edit PEA fields and app screens.
- `custom_pea_shift` controls whether a Stock Entry is a PEA document.

All PEA Stock Entry validate, submit, cancel, mutation, rejection, die-tool, metrics, and cache
side effects must run only when `custom_pea_shift` is set. PEA users must still be able to create
plain ERPNext Manufacture and non-production Stock Entries without triggering PEA logic.

## Local Bench15 Rehearsal
Create a disposable local `bench15` site that mirrors the production customization surface as
closely as practical.

Inputs to copy from production:
- Impacted DocType metadata.
- Custom Fields.
- Property Setters.
- Client Scripts.
- Server Scripts.
- Roles and role permissions relevant to Stock Entry and pilot users.
- Minimal reference data required for workflow testing: Branch, Company, Department, Warehouse,
  Workstation, Item, BOM, Item Alternative, rejected warehouses, and downtime reasons.

Rehearsal sequence:
1. Apply production metadata to the disposable site.
2. Run preflight and record findings.
3. Hide approved legacy fields and disable approved legacy scripts/reports, excluding
   `Stock Entry.branch`.
4. Install and migrate PEA.
5. Keep `PEA User` unassigned and run non-PEA smoke checks.
6. Assign the pilot supervisor `PEA User` and run PEA smoke checks.
7. Produce the final legacy customization removal list with names, types, reason for removal, and
   local verification result.
8. Repeat until the runbook is deterministic.

## Production Cutover
Production cutover is irreversible under current constraints.

Required sequence:
1. Announce and enforce Stock Entry freeze.
2. Run production preflight.
3. Stop if preflight differs materially from the final local rehearsal.
4. Export metadata snapshots for audit/reference.
5. Hide approved legacy fields and disable approved legacy scripts/reports, excluding
   `Stock Entry.branch`.
6. Install and migrate PEA.
7. Keep `PEA User` unassigned and run non-PEA smoke checks.
8. Assign the pilot supervisor `PEA User` and assign `PEA Read Only` to selected reviewers.
9. Run production smoke tests.
10. Reopen Stock Entry usage only after acceptance gates pass.

No destructive production action should happen until the operator explicitly confirms that the
pre-mutation gate passed.

Gurudatt is the explicit go/no-go approver for the first irreversible production action. Approval
requires local rehearsal success, matching production preflight, reviewed legacy action list,
passing branch sample check, and confirmed Stock Entry freeze.

The production window is planned for a holiday. If PEA install fails after the old workflow is
hidden/disabled, troubleshoot for up to two hours with 30-minute checkpoints. If the issue is not
understood after that timebox, manually re-enable/unhide the old workflow and defer rollout.

## Acceptance Gates

### Local Replica Gates
- PEA installs and migrates cleanly after approved legacy fields are hidden and legacy
  scripts/reports are disabled.
- `Stock Entry.branch` remains intact with existing values and expected behavior, verified against
  at least 10 representative submitted Stock Entries or all submitted Stock Entries if fewer than
  10 exist in the replica sample.
- Normal non-PEA Stock Entry create, save, submit, and cancel works.
- PEA Shift create, start, end, and cancel works.
- PEA Shift-to-Stock Entry flow works.
- Rejection and rework flow works with rejected warehouses.
- Die tool counter submit/cancel behavior works.
- Downtime overlap behavior works.
- Existing conflicting scripts are disabled or removed cleanly.
- Full Frappe app tests pass with coverage above 90%.
- Playwright smoke tests pass for affected user-facing flows.
- Final production runbook contains exact commands/actions and a stop point before the first
  destructive production change.
- Rehearsal uses metadata plus a small representative data slice, including real branch,
  company, department, workstation, operator, warehouses, items, BOMs, downtime reasons, and a few
  submitted historical Stock Entries with branch values.

### Production Gates
- Stock Entry users are frozen.
- Pre-mutation checks match the local rehearsal.
- `Stock Entry.branch` metadata and sample values are correct, using the same sample criteria as
  the local rehearsal.
- Approved destructive actions are executed exactly as rehearsed.
- PEA install/migrate completes.
- Pilot user can complete the PEA flow.
- Non-pilot user can complete the normal Stock Entry flow.
- Error logs are checked after smoke tests.

If any pre-mutation check fails, stop before destructive changes.

Stock Entry freeze means all users stop all Stock Entry create, save, submit, and cancel activity
until the cutover smoke tests pass.

Pilot scope:
- One supervisor gets `PEA User` and makes production entries for the pilot shift/workstation.
- Non-PEA users continue non-production Stock Entry purposes such as Material Transfer, Material
  Issue, and Send to Subcontractor.
- Plain ERPNext Manufacture Stock Entries without `custom_pea_shift` remain allowed.

## Testing Strategy
Testing must follow the repository's TDD and coverage requirements.

Unit and integration coverage:
- Preflight conflict detection.
- `Stock Entry.branch` fixture protection.
- Downtime Reason production-schema compatibility.
- Access-control gating for pilot and non-pilot users.
- PEA Read Only role behavior.
- PEA field permlevel read/write behavior.
- Normal Stock Entry passthrough behavior.
- PEA Stock Entry logic does not run when `custom_pea_shift` is blank.
- PEA Stock Entry validation and mutation behavior.
- Controlled/audited Shift branch correction behavior.

E2E coverage:
- Normal Stock Entry flow for a non-pilot user.
- PEA Shift-to-Stock Entry flow for a pilot user.
- Rejection/rework flow.
- Unauthorized user blocked from PEA entry points while retaining native Stock Entry behavior.
- PEA Read Only can view PEA forms/reports but cannot create, edit, submit, or run entry actions.

Manual smoke coverage in local replica and production:
- Branch value preservation.
- Existing production Stock Entry purpose/type scripts after approved removals.
- Submit/cancel behavior.
- Error log review.
- Holiday smoke tests must run as representative users, not only Administrator:
  - pilot supervisor with `PEA User`
  - manager/reviewer with `PEA Read Only`
  - normal Stock Entry user without PEA roles
- Holiday smoke tests must include:
  - controlled PEA production entry using real pilot master data where possible, tiny quantity,
    submit, and cancel
  - one small rejection quantity if the pilot process uses rejection/rework
  - at least one planned or unplanned loss row using an existing/submitted production downtime
    reason
  - normal non-PEA Stock Entry such as Material Transfer
  - plain Manufacture Stock Entry without `custom_pea_shift`

## Operational Trade-offs
- Removing duplicate legacy fields and scripts simplifies the final UI and reduces behavioral
  conflicts, but it is destructive and requires local proof before production.
- Keeping `custom_pea_*` fields avoids a broad field-reuse refactor, but existing users must move
  to the PEA workflow rather than relying on old reports or old time fields.
- Protecting `Stock Entry.branch` reduces risk to existing accounting/branch flows, but PEA must
  adapt around production's existing field ownership.
- Without backup or rollback, the production maintenance window must prioritize stop-before-change
  gates over recovery-after-change.
- Using Frappe permlevels for PEA fields adds fixture/permission work, but is more maintainable
  than relying on client-side hiding as an access boundary.
- Deferring legacy field deletion for one month leaves metadata clutter, but provides a limited
  fallback because hidden fields, disabled scripts, and disabled reports can be restored manually.

## Open Decisions
- Final list of legacy fields/scripts to remove, based on local replica dependency checks.
- Exact production cutover date and maintenance window length.
