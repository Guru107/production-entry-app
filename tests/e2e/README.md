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

## Operation-aware Joint LH/RH

Smoke coverage includes Shearing Joint LH/RH (unchanged common-RM Fetch Items and submit) and a
post-Shearing Joint LH/RH entry that materialises independent per-side source rows and submits.
Regression specs cover stale post-Shearing rows, BOM pair rules, and operating-cost Additional Costs.
Common raw material is Shearing-only; post-Shearing follows two BOM-derived Manufacture calculations
combined into one Repack document (CONTEXT.md "Joint Production", "BOM Sheet Capacity").

`BOM.custom_operation` and `Stock Entry.custom_stock_entry_purpose` are production-owned and are not
shipped by this app; benches and E2E bootstrap copy them as setup (CONTEXT.md "Production-Owned Joint
Metadata").

## Rework and Shift

Rework Operations have no relation to Shift. The browser smoke and regression rework specs assert
that the Shift field is hidden in rework mode. Switching a Manufacture entry that already carries a
Shift to the rework type is not driven through the browser: the client-side clearing is covered by
the JS unit suite and the server-side clearing by the Frappe tests, which is where the rule lives.

## Fetch Items race

Smoke specs should seed Stock Entry rows through the E2E API when Fetch Items is
not the behavior under test. Dedicated coverage for the Desk Fetch Items button
and its route-settling race is tracked in #110.
