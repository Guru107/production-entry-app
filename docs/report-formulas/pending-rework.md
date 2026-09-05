# Pending Rework

Source: `pending_rework/pending_rework.py`

The item summary row uses:

- `Flagged Rework Qty = sum(is_rework Rejection Breakup qty on submitted Production Entries)`
- `Derived Pending Qty = Flagged Rework Qty - submitted Rework Operation item qty`
- `Rejection Warehouse Balance = sum(Bin.actual_qty for the rejection warehouses used by the item's contributing entries)`
- `Pool - Warehouse = Derived Pending Qty - Rejection Warehouse Balance`

Indented rows break the flagged quantity down by contributing Production Entry, Rejection Reason, and Rejection
Warehouse. Rework Operations consume a fungible item pool, so those source rows explain where the flagged quantity
came from; they do not claim that a later Rework Operation consumed a specific source entry or reason.

The derived pool and warehouse balance intentionally differ after a manual scrap write-off. Manual scrap Repacks
reduce physical stock in the Rejection Warehouse, but they are outside the Rework Operation lifecycle and therefore
do not reduce the derived pending pool. Showing both values keeps logical rework demand distinct from physical stock.
