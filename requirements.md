# Enhancement of Production Entry App

### Stock Entry DocType Enhancement

- Add shift reference number field below Stock Entry Type. The field should be editable and optional.
- There must be an action button in the Shift DocType called "Create Production Entry". It should create a Stock Entry Document with the shift reference field prefilled.
- On setting the shift reference field, it must automatically fetch "branch", set "custom_pea_planned_start_date" and "custom_pea_planned_end_date" from the shift document. Assume that these fields are already available in the stock entry document.
- There are fields called "custom_pea_planned_start_date" and "custom_pea_planned_end_date" in the stock entry doctype, those must be pre-filled with shift start date time and end date time as these are DateTime fields.
- Branch field must be prefilled from shift document.
- Add Loss Entry doctype in Stock Entry in a separate section to capture unplanned loss entries.
- Refactor Loss Entry doctype and change the Link field "loss_type" to point to "Downtime Reason" doctype. Remove the Loss Type DocType. Add a remark field in Loss Entry doctype.
- Update all references to Loss Entry doctype and update all tests referencing the doctype.
- Set the "from_warehouse" and "to_warehouse" in the Stock Entry doctype if the shift reference field is given. The source for this field should be "work_in_progress_warehouse".
- Add a field Operator in "Operation Details" section. Operator must be a doctype that will contain name and is_active field.
- "Operation Details" will have the following fields,
  - "custom_pea_planned_start_date" (Shift Planned start date time)
  - "custom_pea_planned_end_date" (Shift Planned end date time)
  - "custom_pea_actual_start_date" (Supervisor enters)
  - "custom_pea_actual_end_date" (Supervisor enters)
  - "custom_pea_workstation" (Link)
  - "custom_pea_standard_spm" (Fetch from Workstation)
  - "operator" (Link) - Link to Operator DocType
- Find a way to define rejection entries in the same manufacturing stock entry. Once user enters "fg_completed_qty" and clicks on "get_items". The stock entry detail gets populated based on BOM calculation. There must be a way to set rejection quantity so that it gets deducted from final quantity in stock entry detail and another row must get inserted where the target warehouse is rejection store.



