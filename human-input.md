## Improvements to Production Entry App

- Restructure the layout of the shift page, and make it compact, add vertical tabs so that there are two sections. Segregate sections and group existing fields according to sections. Right now all fields are one below the other and there is no proper structure.

- When we create a production entry and link it to a running shifts there has to be certain
validations like if a workstations/operator are already occupied between actual start and actual end then they should not be assignable to other production entry during that time frame.

- If there is a downtime entry for a workstation for a period of time which overlaps with the shift, it must not be usable for that downtime time period.

- Appropriate messages must be shown for all validations.

- On the workstation and operator doctypes, add a horizonatal bar visualization of the currently running shift which will have planned start and planned end time labels at the start and end edges. The bar should be grey in background color. All production entries that are linked to that workstation/operator in that running shift must have a vertical time slice of a unique vibrant color with the width equivalent to the actual start and actual end times. This horizontal bar will give an overview of time slices consumed for the production entries. On hovering over any time slice it must show a tool tip that will have fg item code from the bom used, Fg qty, rejection qty and ok qty. This will give birds eye view of the current shift.

- There must also be a shift metrics sections that will be the aggregate of production metrics in that shift.
