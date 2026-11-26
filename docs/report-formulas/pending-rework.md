# Pending Rework

Source: `pending_rework/pending_rework.py`

One summary row per Company, Branch and Item (the Pending Rework Pool bucket; Branch is blank where the host has
no `Stock Entry.branch`). Optional Company, Branch and Item filters narrow the buckets. The summary row uses:

- `Flagged Rework Qty = sum(is_rework Rejection Breakup qty on submitted Production Entries of the bucket)`
- `Derived Pending Qty = Flagged Rework Qty - submitted Rework Operation item qty of the bucket`
- `Rejection Warehouse Balance = sum(Bin.actual_qty for the rejection warehouses used by the bucket's contributing entries)`
- `Pool - Warehouse = Derived Pending Qty - Rejection Warehouse Balance`

When branches of one Company share a rejection warehouse, each branch row shows that warehouse's full Bin balance.

Indented rows break the flagged quantity down by contributing Production Entry, Rejection Reason, and Rejection
Warehouse. Rework Operations consume a fungible item pool within their Company and Branch, so those source rows explain where the flagged quantity
came from; they do not claim that a later Rework Operation consumed a specific source entry or reason.

The derived pool and warehouse balance intentionally differ after a manual scrap write-off. Manual scrap Repacks
reduce physical stock in the Rejection Warehouse, but they are outside the Rework Operation lifecycle and therefore
do not reduce the derived pending pool. Showing both values keeps logical rework demand distinct from physical stock.
