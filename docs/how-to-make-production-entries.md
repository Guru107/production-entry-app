# How to Make Production Entries — Demo Guide

This guide walks a supervisor through every type of entry in the **Production Entry App**, an ERPNext module that turns the native **Stock Entry** into a complete production record: material consumption, output, rejections, losses, downtime, press strokes and operator time — all tied to a **Shift**.

Everything starts from the **Production Entry App** workspace, which has two cards:

- **Forms:** Stock Entry, Shift, Operator, Die Tool Counter, Die Tool Maintenance Log, Rejection Reason, Downtime Entry
- **Reports:** Production OEE, Monthly OEE, Workstation / Operator Efficiency, Rejection & Rework Pareto / PPM / Trend reports, Pending Rework, Daily Rej Rework Register, Die Tool reports, and more

> **Roles:** users need the **PEA User** role to create entries; **PEA Read Only** gives read/report access only.

---

## 0. One-time setup (masters)

Before the first entry, make sure these exist:

| Master | Where | What to set up |
|---|---|---|
| **Production Entry Settings** | Awesome Bar → "Production Entry Settings" | One **Branch Warehouse Defaults** row per Company + Branch (Raw Material, Work In Progress, Rejection, Scrap warehouses). Shift Start/End Buffer (minutes) control how far outside the planned window entries are accepted. Optionally set the **Rework Expense Account**. |
| **Operator** | Workspace → Operator | Operator Name, Is Active. |
| **Downtime Reason** | (seeded) | Standard coded reasons (00 Other, 01 Setup, 03 No Operator, 04 No Material, 05 Maintenance, …). Custom reasons use free codes 23–98. |
| **Rejection Reason** | Workspace → Rejection Reason | Reason name, Is Active. |
| **Rework Type** | Awesome Bar → "Rework Type" | e.g. "Deburring"; optionally a Default Workstation. |
| **Workstation** | Stock → Workstation | Set the **Standard SPM** — it is fetched onto entries and drives OEE targets. |
| **Stock Entry Types** | Awesome Bar → "Stock Entry Type" | Your Manufacture types (e.g. "1st Forming"), plus the app-shipped **Joint LH RH Production** (Repack) and **Rework** (Material Transfer). |
| **BOM** | Manufacturing → BOM | Active default BOMs for the items you will produce. |

---

## 1. Create and start a Shift

The Shift is the anchor for all production reporting. Entries linked to a Shift inherit its company, branch, planned window and warehouses.

1. Workspace → **Shift** → **New**.
2. On the **Overview** tab fill:
   - **Shift Label** (1 or 2)
   - **Shift Duration (Hours)** (8 / 10 / 12 / 14 / 16)
   - **Shift Date** (a *Today* shortcut is available)
   - **Planned Start Time** — type HH:MM (e.g. 0630) or click a preset chip (06:00, 08:00, 14:00, …) or **Now**
   - **Department** and **Branch** (Company appears when you have more than one)
   - Shift End Date and Planned End Time compute automatically.
3. **Warehouses** tab: Raw Material / Work In Progress / Rejection / Scrap warehouses are pre-filled from Production Entry Settings for the Company + Branch; adjust only if this shift differs. A Shift's explicit values always win over settings.
4. **Breaks** tab: **Planned Losses** (e.g. lunch, tea breaks) are auto-populated once date, duration and start time are set. Edit them while the Shift is in *Draft*.
5. **Save**, then **Actions → Start Shift**. Status: Draft → Running.

Other Shift actions:

- **Actions → End Shift** — ends the shift (Running → Completed). You can still add post-facto entries afterwards; they are flagged as **Late Entry (Post-Completion)**.
- **Actions → Cancel** — available in Draft and Completed.
- The only edit a Completed Shift accepts is a **larger Shift Duration** (planned losses are regenerated for the longer window).
- **Create → Downtime Entry** / **Create → Production Entry** — shortcut buttons that pre-fill the Shift.

The **Summary** tab (read-only) shows the Outcome Snapshot — entries, late-entry count, total / OK / rejection qty, rejection %, recorded production minutes, throughput SPM, target coverage, shift efficiency — plus loss and variance minutes and top loss/downtime reasons. The **Activity** tab lists linked Downtime Entries.

---

## 2. Make a Production Entry (normal Manufacture, with Shift)

This is the everyday entry: one BOM, one finished item.

1. From the Running/Completed Shift, click **Create → Production Entry** — or create a **Stock Entry** manually and set **Stock Entry Type** to a *Manufacture* type (e.g. "1st Forming").
2. **Shift**: pick the shift (the dropdown lists only Running/Completed shifts). Selecting it auto-fills Company, Branch, Department, **Planned Start/End Date**, and — unless a Work Order is linked — the source/target warehouses from the Shift (production consumes from **WIP**, not raw material).
   > All production sections stay **hidden until a Shift is selected**. Clearing the Shift wipes them.
3. Keep **From BOM** checked, pick the **BOM No**, and set **Qty To Manufacture** (gross quantity produced).
4. **Rejection Quantity** (just below Qty To Manufacture): how many of the produced parts were rejected. **OK Qty** computes automatically (FG Qty − Rejection Qty). Rejected qty is routed to the **Rejection Warehouse** as a separate item row on fetch.
5. **Operation Details** (required once a Shift is set):
   - **Actual Start / End Date + Time** — date field plus an HH:MM quick-entry time field; they combine into the read-only Actual Start/End datetimes.
   - **Workstation** — **Standard SPM** is fetched from it.
   - **Operator** — link to the Operator master.
6. Click **Fetch Items** (the native *Get Items* is hidden by the app). The Items table is rebuilt from the BOM: raw materials from WIP, the finished good at **OK Qty**, rejection qty as a separate row flagged **Is Rejection Item** into the Rejection Warehouse, and scrap into the Scrap Warehouse. Fetching replaces the table, so re-fetch after changing quantities.
7. **Rejection Breakup** (mandatory when Rejection Quantity > 0): one row per cause — **Rejection Reason**, **Qty**, tick **Rework** if the parts can be reworked later, optional Remark. Breakup quantities must cover the rejection quantity. The sum of rows flagged *Rework* shows as **Rework Quantity** (this feeds the **Pending Rework** pool).
8. **Unplanned Losses**: one row per stoppage during production — **Downtime Reason** (required), **Remark**, and any two of **Start / Mins / End** (the third computes).
9. **Total Press Strokes** auto-defaults to Qty To Manufacture for BOM-based entries and must be > 0; adjust if one stroke produces multiple parts.
10. **Save** and **Submit**. The **Production Metrics** section then shows Actual Duration, Production Time, Actual SPM, Cycle Time, Operator Efficiency %, and Die Tool Utilization %.

> **Die tool alert:** if the die reaches its warning threshold, an orange headline appears: "Die tool {item} has reached {x}% utilization and needs maintenance." Log the maintenance in **Die Tool Maintenance Log** to reset the counter.

**Stock-only entry:** create a Manufacture entry *without* a Shift — it behaves like native ERPNext (no time/loss/metrics capture) and is excluded from shift summaries and OEE reports.

---

## 3. Log machine Downtime (not tied to one entry)

For workstation stops that are not part of a specific production entry:

1. Shift → **Create → Downtime Entry** (Shift pre-filled), or workspace → **Downtime Entry** → New.
2. Fill **Workstation**, **From Time** and **To Time** (From must be before To), the **Operator** if known, and the app's required **Downtime Reason** link.
3. Save. These minutes appear on the Shift's **Activity** tab and count as **Machine Downtime** in OEE — each minute counts once, separate from planned losses and per-entry unplanned losses.

---

## 4. Joint LH/RH Production (one press stroke, two paired parts)

For stamping operations that produce Left-Hand and Right-Hand parts together:

1. New Stock Entry → **Stock Entry Type = Joint LH RH Production** (a Repack type). The form switches to joint mode: **Operation** becomes mandatory and the single-mode rejection fields are hidden.
2. Select the **Shift** (company, branch, dates, warehouses auto-fill as usual).
3. **Operation**: pick the operation (e.g. Shearing). For **Shearing**, both sides consume proportional shares of one common raw-material sheet; for any other operation each side consumes its own BOM inputs independently.
4. **Joint LH/RH Production** section: pick the **LH BOM** and **RH BOM**, enter each side's **Gross Quantity** and **Rejection Quantity**, then click **Fetch Items**. The app materializes both sides' consumption, outputs and rejection rows (each row tagged **Joint Output Side** LH/RH).
5. **Operation Details**: actual times, **Workstation**, **Operator**, then **Total Press Strokes** (one count for the shared press operation — it may differ from either side's quantity) and **Die Tool Item** (required when a Shift is set; drives utilization tracking).
6. **Rejection Breakup** rows in joint mode require **Output Side**; the Item Code auto-fills from that side's BOM finished item.
7. Save and Submit.

---

## 5. Rework Entry (recover rejected parts)

Rejected quantities flagged **Rework** accumulate in the **Pending Rework** pool (per item). To rework them:

1. New Stock Entry → **Stock Entry Type = Rework** (a Material Transfer type). Any Shift link is dropped — rework is not shift-managed.
2. The **Rework Details** section appears: **Rework Type** (e.g. Deburring), **Rework Workstation** (defaults from the Rework Type), and the **Rework Operators** table — one row per operator with their own **Actual Start / Actual End**.
3. Source warehouse defaults to the **Rejection Warehouse** (from Company + Branch defaults). Move the reworked qty to the good warehouse.
4. Submit. Labour cost is computed from the sum of per-operator time × Workstation hour rate and loaded onto the stock as one **Additional Cost** row (credited to the Rework Expense Account or the company's Default Operating Cost Account).
5. Track what remains in the **Pending Rework** report; rejection and rework history is in the **Daily Rej Rework Register**. Rework entries are excluded from OEE (rework-flagged qty already counted as a quality loss at production time — "right first time").

---

## 6. End the Shift and read the results

1. Shift → **Actions → End Shift**. Late entries made afterwards still link to the shift and are flagged **Late Entry (Post-Completion)**.
2. Review the Shift **Summary** tab.
3. Reports (workspace → Reports) use the **Production Date** = the Completed Shift's date, not the posting date:
   - **Production OEE Report** / **Monthly Production OEE Report** — Availability, Productivity, Quality, OEE per workstation, with per-reason loss breakdown.
   - **Workstation / Operator Efficiency**, **Operator Daily SPM**, **Daily Strokes SPM Monitor**.
   - **Rejection / Rework Pareto, PPM, Trend** reports, reason matrices, and Item/BOM hotspots.
   - **Pending Rework**, **Daily Rej Rework Register**, **Die Tool Stroke and Maintenance Report**.

---

## Quick reference — demo cheat sheet

| Step | Do this |
|---|---|
| 1 | Masters ready: Operator, Downtime/Rejection Reasons, Workstation SPM, BOMs, Branch warehouse defaults in Production Entry Settings |
| 2 | Shift → New → label, duration, date, start time, department, branch → Save → **Start Shift** |
| 3 | Shift → **Create → Production Entry** → Manufacture type, BOM, Qty, Rejection Qty |
| 4 | Actual start/end, Workstation, Operator → **Fetch Items** |
| 5 | Rejection Breakup rows (reason, qty, rework?) + Unplanned Losses rows (reason, start/mins/end, remark) |
| 6 | Save → **Submit** → check Production Metrics |
| 7 | Machine stops outside entries → **Downtime Entry** with reason |
| 8 | Paired LH/RH parts → Stock Entry Type **Joint LH RH Production** |
| 9 | Recover rejected parts → Stock Entry Type **Rework** |
| 10 | **End Shift** → Shift Summary → OEE and rejection reports |

### Common gotchas

- **"Please set Qty to Manufacture before fetching items."** — set the quantity before clicking Fetch Items.
- Production sections invisible? **Select a Shift first** — they are shift-gated.
- Rejection Quantity > 0? The **Rejection Breakup table is mandatory** and its quantities must match.
- Changing Stock Entry Type **clears** the other mode's data (shift fields vs joint vs rework) — pick the type first.
- Warehouses missing on fetch? Check the **Branch Warehouse Defaults** row for the Company + Branch in Production Entry Settings — there is no global fallback by design.
