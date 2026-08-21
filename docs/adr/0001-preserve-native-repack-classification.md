# Preserve native Repack item classification

Joint Production uses ERPNext's native Repack Stock Entry lifecycle. The app must preserve ERPNext's item classification, valuation, additional-cost allocation, Stock Ledger, and General Ledger behaviour, including cases where a scrap row with a target warehouse is also marked as a finished item. App-owned calculations and reports must identify scrap independently of `is_finished_item` and exclude it whenever the intended measure is good production output.

## Considered Options

- Normalize scrap rows by clearing `is_finished_item` after ERPNext classifies Repack items. This was rejected because it overrides native semantics and may change valuation, additional-cost distribution, and ledger dependencies.
- Preserve native classification and make app consumers distinguish good output, rejection, and scrap explicitly. This keeps the integration seam narrow and ERPNext-owned behaviour intact.

## Consequences

The Joint Production module must not rewrite native Repack classification flags during validation, save, or submit. Tests may assert that a scrap row carries both native finished-item classification and its scrap marker or type. Any app query or calculation that means "good output" must require a non-rejection, non-scrap row rather than relying on `is_finished_item` alone.
