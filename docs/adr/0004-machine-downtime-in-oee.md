# Count uncovered Downtime Entry minutes in OEE

A stop recorded only as a Downtime Entry was invisible to the Production OEE Report, so Availability stayed high while the press was down. Machine Downtime is the minutes of a Downtime Entry on that workstation during a Completed Shift that fall outside planned Shift losses and outside Loss Entries on Production Entries. Each minute counts once. Those hours are one column. Where Production Entries exist, they shorten running time, and Productivity uses that shorter time. Where the workstation has Machine Downtime and no Production Entry, running time is zero, so Availability and OEE are zero, while the column still shows only the logged hours. An operation filter hides that row.

## Considered Options

- Leave Downtime Entry out of OEE. Rejected because a stop that never becomes a Loss Entry inflates Availability.
- Add every Downtime Entry on top of Loss Entries. Rejected because the same minute would count twice.
- Treat the whole idle shift as Machine Downtime. Rejected because actual production time is zero when nothing was produced, and the column is only the logged slice.
- Split the column by shift, or map native stop reasons onto Downtime Reason buckets. Rejected in favour of one Machine Downtime column.

## Consequences

On a row with Production Entries, Productivity can rise while Availability falls, because both use the running time that remains after Machine Downtime. On a row with no Production Entry, the hours between available time and Machine Downtime are unlabeled. A blank Shift link still counts when the workstation and the shift window match. A filled Shift link must be that Shift. Cancelled Downtime Entries are ignored.
