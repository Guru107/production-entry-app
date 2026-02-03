# Production Entry Module - Final Specification

## Overview

This Frappe Framework application for ERPNext simplifies production entries by introducing a **Shift** document that acts as a central hub for supervisors to manage shift-related information.

---

## 1. Shift DocType

### 1.1 Core Fields

| Field | Type | Description |
|-------|------|-------------|
| Shift Label | Select | Fixed options: "Shift 1", "Shift 2" |
| Shift Duration | Select | Fixed options: 8, 10, 12 hours |
| Shift Date | Date | Start date of shift (default: current date) |
| Shift End Date | Date | Derived field for shifts crossing midnight |
| Planned Start Time | Time | Default: current time |
| Planned End Time | Time | Readonly, derived: Planned Start Time + Shift Duration |
| Supervisor | Link (User) | Auto-captured from current logged-in user |

### 1.2 Default Warehouses Section

| Field | Type | Description |
|-------|------|-------------|
| Raw Material Warehouse | Link (Warehouse) | Copied from Manufacturing Settings on creation |
| Work In Progress Warehouse | Link (Warehouse) | Copied from Manufacturing Settings on creation |
| Rejection Warehouse | Link (Warehouse) | Copied from Manufacturing Settings on creation |
| Scrap Warehouse | Link (Warehouse) | Copied from Manufacturing Settings on creation |

> Supervisors can modify these warehouse values as needed for their shift.

### 1.3 Naming Series

Format: `SHIFT-YYYY.MM.DD.Shift-{N}`

Examples:
- `SHIFT-2026.02.03.Shift-1`
- `SHIFT-2026.02.03.Shift-2`

---

## 2. Loss Type DocType (New Master)

A separate master DocType to manage predefined loss types.

### 2.1 Fields

| Field | Type | Description |
|-------|------|-------------|
| Loss Type Name | Data | Name of the loss type (e.g., "Tea Break", "Lunch Break") |
| Default Duration | Int | Default duration in minutes |

### 2.2 Default Loss Types

| Loss Type | Default Duration |
|-----------|------------------|
| Tea Break | 15 minutes |
| Lunch Break | 30 minutes |

---

## 3. Planned Losses (Child Table in Shift)

### 3.1 Fields

| Field | Type | Description |
|-------|------|-------------|
| Loss Type | Link (Loss Type) | Selected from Loss Type master |
| Start Time | Time | Start time of the loss |
| End Time | Time | End time of the loss |

### 3.2 Auto-Population Rules

When a supervisor selects a shift duration, the planned losses table auto-populates with fixed time offsets from the Planned Start Time.

#### 8-Hour Shift (45 minutes total loss)

| Loss Type | Offset from Start | Duration |
|-----------|-------------------|----------|
| Tea Break | +2 hours | 15 minutes |
| Lunch Break | +4 hours | 30 minutes |

#### 10/12-Hour Shift (60 minutes total loss)

| Loss Type | Offset from Start | Duration |
|-----------|-------------------|----------|
| Tea Break | +2 hours | 15 minutes |
| Lunch Break | +4 hours | 30 minutes |
| Tea Break | +6 hours | 15 minutes |

### 3.3 Editability Rules

- **Draft status**: Fully editable (add, remove, modify losses)
- **Running status**: Locked (not editable)
- **Completed status**: Locked (not editable)

---

## 4. Downtime Entry Integration

### 4.1 Custom Field on Downtime Entry

| Field | Type | Description |
|-------|------|-------------|
| Shift | Link (Shift) | Optional link to associate downtime with a shift |

### 4.2 Display in Shift Document

- Shift document displays linked Downtime Entries in a section
- Uses Frappe's linked documents feature or virtual field

---

## 5. Manufacturing Settings Customization

### 5.1 New Tab: Shift Settings

Add a new tab called "Shift Settings" to the Manufacturing Settings DocType via **Custom Fields** (fixtures).

### 5.2 Fields in Shift Settings Tab

| Field | Type | Description |
|-------|------|-------------|
| Raw Material Warehouse | Link (Warehouse) | Default raw material warehouse for shifts |
| Work In Progress Warehouse | Link (Warehouse) | Default WIP warehouse for shifts |
| Rejection Warehouse | Link (Warehouse) | Default rejection warehouse for shifts |
| Scrap Warehouse | Link (Warehouse) | Default scrap warehouse for shifts |

---

## 6. Workflow & State Transitions

### 6.1 States

```
Draft → Running → Completed
         ↓
      Cancelled
```

| State | Description |
|-------|-------------|
| Draft | Initial state, all fields editable |
| Running | Shift in progress, losses locked |
| Completed | Shift ended, fully locked |
| Cancelled | Shift cancelled before starting |

### 6.2 Transition Triggers

| Transition | Trigger |
|------------|---------|
| Draft → Running | Manual "Start Shift" button click |
| Running → Completed | Manual "End Shift" button click |
| Draft → Cancelled | Manual "Cancel" action |

### 6.3 Field Locking Rules

| State | Editable Fields |
|-------|-----------------|
| Draft | All fields editable |
| Running | Planned Losses locked; other fields may be editable |
| Completed | Entire document locked |
| Cancelled | Entire document locked |

---

## 7. Validation Rules

### 7.1 Global Overlap Prevention

- No two shifts can have overlapping time periods
- Validation runs on save/submit

### 7.2 Unique Shift Label per Date

- Only one "Shift 1" allowed per date globally
- Only one "Shift 2" allowed per date globally
- Prevents duplicate naming conflicts

### 7.3 Midnight Crossing

- If Planned End Time crosses midnight, Shift End Date is automatically set to the next day
- Example: Start at 10:00 PM on Feb 3 with 10-hour duration → End Date = Feb 4

---

## 8. Permissions

### 8.1 Role-Based Access

| Role | Create | Read | Write | Delete |
|------|--------|------|-------|--------|
| Manufacturing User | ✓ | ✓ | ✓ | ✓ |
| Manufacturing Manager | ✓ | ✓ | ✓ | ✓ |

---

## 9. UI/UX Requirements

### 9.1 Responsive Design

- Shift document must be mobile-friendly
- Easy to create and edit on phone screens
- Large touch targets for buttons
- Simplified layout for mobile view

### 9.2 Action Buttons

- "Start Shift" button (visible in Draft state)
- "End Shift" button (visible in Running state)
- "Cancel" button (visible in Draft state)

---

## 10. Out of Scope (Future Phases)

The following features are explicitly excluded from this phase:

1. **Production Entry Link**: Linking Stock Entry (Manufacture type) to Shift documents
2. **Actual Loss Tracking**: Tracking actual vs planned loss durations
3. **Workstation Association**: Linking shifts to specific workstations
4. **Custom Shift Labels**: Adding more shift labels beyond Shift 1/Shift 2
5. **Custom Shift Durations**: Adding durations beyond 8/10/12 hours

---

## 11. Technical Implementation Notes

### 11.1 DocTypes to Create

1. **Loss Type** (Master)
2. **Shift Planned Loss** (Child Table)
3. **Shift** (Main Document)

### 11.2 Custom Fields to Add

- Manufacturing Settings: 4 warehouse fields in "Shift Settings" tab
- Downtime Entry: 1 "Shift" link field

### 11.3 Fixtures Required

- Custom Fields for Manufacturing Settings
- Custom Fields for Downtime Entry
- Default Loss Type records (Tea Break, Lunch Break)

---

## 12. Acceptance Criteria

1. Supervisor can create a new Shift document with default values populated
2. Planned losses auto-populate based on selected shift duration
3. Warehouses copy from Manufacturing Settings on new shift creation
4. Shift transitions through Draft → Running → Completed states correctly
5. Planned losses lock when shift moves to Running state
6. System prevents overlapping shifts
7. System enforces unique shift label per date
8. Downtime Entries can optionally link to a Shift
9. Shift document is usable on mobile devices
10. Midnight-crossing shifts correctly calculate end date
