# Production Entry Module for ERPNext

## Shift DocType

Create a shift document, this document will be used by supervisor to create shift at the start of his shift.
This will act as a central place to get all the information related to the shift, it will ease the operation of the supervisor.
The shift document must contain the below fields,

Shift Label:  Shift 1/Shift 2
Shift Duration: 8/10/12 hrs
Shift Date: by default current date(Date field type)
Planned Start Time: by default current time(Time field type)
Planned End Time: Readonly field which will be a derived from Planned Start Time + Shift duration.(Time field type)


Planned Losses in a Shift
8 hrs shift - 45 Minutes Loss
Tea Break: 15 Minutes
Lunch Break: 30 Minutes

10/12 hrs shift - 60 Minutes Loss
Tea Break: 15 Minutes
Lunch Break: 30 Minutes
Tea Break: 15 Minutes

The Loss Table Fields
Loss Type: (Pre-defined Losses selected from the drop-down) - Supervisor must have ability to add new Loss Types
Start Time: Start Time of Loss
End Time: End Time of Loss

When a supervisor selects a duration, planned losses table must get populated according to the shift duration selected.

Shift document must have the ability to add Downtime Entry.
Downtime Entry is a core ERPNext DocType which records workstation downtime.

Default Warehouses
Manufacturing Settings DocType Changes
- It must contains a new tab called Shift Settings
  Shift Settings Defaults
  - Raw Material Warehouse(Link)
  - Work In Progress Warehouse(Link)
  - Rejection Warehouse(Link)
  - Scrap Warehouse(Link)

Shift Document must also contain default warehouses
When a new shift is created by the supervisor, all default warehouses must get copied from Manufacturing Settings
  - Raw Material Warehouse(Link)
  - Work In Progress Warehouse(Link)
  - Rejection Warehouse(Link)
  - Scrap Warehouse(Link)
The supervisor has the authority to change any of the 4 in the shift document according to his needs.

Shift Doctype will transition from Draft -> Running -> Completed.

Once the document is in running status, planned losses must no longer be editable.
Once Shift is marked as completed it must no longer be editable.

Shift Naming Series: SHIFT-YYYY.MM.DD.ShiftLabel

The Shift document must be responsive, it must be easy to create and edit shift document on a phone as well.
