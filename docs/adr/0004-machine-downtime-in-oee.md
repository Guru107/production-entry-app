# Count uncovered Downtime Entry minutes in OEE

A stop recorded only as a Downtime Entry was invisible to the Production OEE Report, so Availability stayed high while the press was down. Machine Downtime is the minutes of a Downtime Entry on that workstation during a Completed Shift that fall outside planned Shift losses and outside Loss Entries on Production Entries. Each minute counts once. Those hours are one column. Where Production Entries exist, they shorten running time, and Productivity uses that shorter time. Where the workstation has Machine Downtime and no Production Entry, running time is zero, so Availability and OEE are zero, while the column still shows only the logged hours. An operation filter hides that row.

## Considered Options

- Leave Downtime Entry out of OEE. Rejected because a stop that never becomes a Loss Entry inflates Availability.
- Add every Downtime Entry on top of Loss Entries. Rejected because the same minute would count twice.
- Treat the whole idle shift as Machine Downtime. Rejected because actual production time is zero when nothing was produced, and the column is only the logged slice.
- Split the column by shift, or map native stop reasons onto Downtime Reason buckets. Rejected in favour of one Machine Downtime column.

## Consequences

On a row with Production Entries, Productivity can rise while Availability falls, because both use the running time that remains after Machine Downtime. On a row with no Production Entry, the hours between available time and Machine Downtime are unlabeled. A blank Shift link still counts when the workstation and the shift window match. A filled Shift link must be that Shift. Cancelled Downtime Entries are ignored.

Amended (#259): a row's available time also counts every Completed Shift whose Machine Downtime the row counts, once per shift. Without it, downtime from a shift with no Production Entry on the row could exceed the available time and zero Availability. Downtime with a Shift link adds that shift's available time. Downtime with no Shift link matches every Completed Shift window it overlaps, across branches and departments, because a Workstation has neither. Those shifts add the union of their windows, less their planned losses and less the windows of shifts already counted on the row, so each clock minute counts once. Two branches running the same Shift 1 add one shift's available time, not two. Production Entry Loss Entry times are dated against the entry's shift window, so same-reason losses on either side of midnight merge instead of counting twice.
