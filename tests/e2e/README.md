# E2E scope notes

## Stock Entry Branch layout

`Stock Entry.branch` is owned by the production instance, not by this app. The app
does not create that custom field and does not guarantee its Desk layout position.

Browser coverage for `Stock Entry.branch` placement is intentionally waived here.
This app's responsibility is limited to a guarded handoff: when the production
instance provides `Stock Entry.branch`, selecting a Shift copies the app-owned
`Shift.branch` value into it; when the field is absent, the handoff is skipped
safely. That contract is covered by server-side tests.

## Joint/Repack overlap validation

Browser coverage includes a Joint/Repack resource-overlap popup smoke test. Focused Frappe tests also
save real Joint/Repack Stock Entries and verify overlap, resave, cancelled-entry, adjacent-window, and
downtime behavior.
