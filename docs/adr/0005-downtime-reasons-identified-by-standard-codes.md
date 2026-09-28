# Downtime Reasons are identified by standard codes, not names

Downtime Reason masters were named by their description ("Setup Time", "Power Off"), and the Production OEE Report mapped those names onto fixed loss buckets through a hardcoded dictionary that silently dropped any reason it did not list. The plant standard gives every cause a two-digit code, so the Downtime Reason document name is now that code and a separate editable description carries the human-readable name. Selection matches the code or the description; grids display the description. The standard set spans 00-22, including the planned-loss masters (Shift Start Up 10, JH Activity 13, Tea Break 14, Lunch Break 19, Dinner 20); there is no 99. A migration renamed existing documents to their codes — Frappe cascades those renames into Loss Entry rows on submitted Shifts and Production Entries — and replaced Mtrl Handl, Tool Break and No Helper with Other (00) before deleting them. The fixed OEE buckets and the name-to-bucket dictionary were removed with the names; the breakdown is now chosen per report filter.

## Considered Options

- Keep description-named documents and add a code as a secondary field. Rejected because identity would stay with a free-text name while the standard speaks in codes.
- Keep old names as document names and surface codes only in search. Rejected because stored names like "Power Off" would permanently disagree with standard descriptions like "No Power".
- Retain Mtrl Handl, Tool Break and No Helper as inactive masters. Rejected because they are outside the standard; entries that referenced them resolve to Other (00) and users can recreate a reason if one is genuinely needed.

## Consequences

Document names are numeric ("01", "11"), so anything that reads raw IDs — scripts, patches, report filters — must use codes even though users never see them; grids and link previews show descriptions. The OEE breakdown no longer has fixed columns: with no reasons selected the report shows only Machine Downtime, Total Loss Time and Running Time, and every selected reason contributes a 1st/2nd Shift column pair whether or not data exists. Reasons left out of the filter fold into Total Loss Time only. Planned-loss generation uses the codes, so deleting a master again silently stops generating those rows, the same skip-if-missing behaviour as before.
