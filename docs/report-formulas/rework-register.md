# Rework Register

Source: `rework_register/rework_register.py`

Each row represents one submitted Stock Entry whose Stock Entry Type is marked as a Rework Entry.

- `Date = Stock Entry posting_date`. Rework Operations are not linked to a Shift, so the register does not use
  Production Date.
- `Items + Qty` lists each Stock Entry Detail item and its quantity in child-row order.
- `Total Qty = sum(Stock Entry Detail qty)`.
- `Duration (Hours) = (Rework Actual End - Rework Actual Start) / 3600`.
- `Operators` lists the named Rework Operator rows in child-row order.
- `Operator Count = count(named Rework Operator rows)`.
- `Computed Cost = stored Stock Entry custom_pea_rework_cost`. The report does not recalculate historical cost
  from current Workstation rates.

The report footer sums Total Qty, Duration (Hours), Operator Count, and Computed Cost across the filtered rows.
Date, Rework Type, Item, and Workstation filters restrict which submitted Rework Operations are included.
