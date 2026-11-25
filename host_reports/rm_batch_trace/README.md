# RM Batch Trace (host report)

A **non-standard Script Report** on the host ERPNext site that answers: which raw-material
batches went into the quantity on this Sales Invoice? It is **not part of
`production_entry_app`**. Nothing here is installed with the app. The source lives in this repo
so it gets reviewed, and it reaches a site through the REST API. See issue #291.

| File | What it is |
|---|---|
| `rm_batch_trace.py` | The `report_script` body. It runs in Frappe's `safe_exec` (RestrictedPython) |
| `rm_batch_trace.js` | The Report's `javascript`: the filters (Branch, then Sales Invoice, then optional Item) |
| `report.json` | The Report document: roles (Stock User, Stock Manager), ref doctype |
| `publish.py` | Creates or updates the Report by name on staging or production |
| `test_rm_batch_trace.py` | Tests that run the report through the real sandbox on a dev site |

## Filters

Pick a **Branch** first. The **Sales Invoice** dropdown then lists only that branch's submitted,
stock-updating, non-return invoices; the script refuses an invoice from another branch. **Item**
is optional and limits the trace to that item's lines. Only stock-updating Sales Invoices are
supported for now. Invoices whose stock moved on a Delivery Note are refused with a message.

Users need read access to the Sales Invoice as well as a report role. On production, Stock User
alone cannot read Sales Invoices.

## How it traces

Per (item, warehouse) it walks the Stock Ledger first-in-first-out, using deltas of
`qty_after_transaction` (Stock Reconciliation posts `actual_qty = 0`). Each SLE is tied to its
voucher row through `voucher_detail_no`. From an incoming entry it follows:

- **transfer row:** the same slice out of the source warehouse;
- **output of a Manufacture or Repack entry:** the same share of the inputs. Joint entries
  (rows tagged LH/RH/BOM n) split shared inputs by each line's BOM-derived demand;
- **End Piece** (a scrap row whose item is *not* in the "Scrap" item group): its kg onto the
  producing entry's same-unit inputs. Items in the "Scrap" group stop as *Untraced: Scrap*;
- **Subcontracting Receipt:** the supplied items out of the supplier warehouse;
- **batch-tracked item:** stop and split by the batches recorded on the consuming entry;
- anything else (Purchase Receipt, Material Receipt, Stock Reconciliation increase, opening
  balance) is listed as *Untraced* with the voucher where tracing stopped.

## Run the tests

From the bench's `sites` folder, against a dev site (everything is rolled back):

```bash
cd /root/workspace/bench15/sites
../env/bin/python ../../production-entry-app/host_reports/rm_batch_trace/test_rm_batch_trace.py development.localhost
# a single test: append its method name(s)
```

## Publish

The API user needs the **Script Manager** role. `--target` has no default.

```bash
python host_reports/rm_batch_trace/publish.py --target staging      # ERPNEXT_STAGING_* env vars
python host_reports/rm_batch_trace/publish.py --target production   # ERPNEXT_* env vars (maintainer only)
```

Running it again updates the same Report. If a run takes over 15 s, Frappe switches the report
to a background Prepared Report on its own.

## Editing the script: sandbox rules

`safe_exec` in Frappe v15 rejects or lacks the following. The tests catch each of them:

- imports, and names or attributes starting with `_` (the translation function `_` is fine);
- top-level functions seeing other top-level names. Everything lives inside `rm_batch_trace()`;
- tuple-unpacking assignment (`a, b = ...`; unpacking in `for` loops is fine);
- `d[k] += x`, `str.format()`, and subscript reads of string keys starting with `_` (use `.get()`);
- `frappe.has_permission`. Use `frappe.get_list` to check that the user can read a document.
