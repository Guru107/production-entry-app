# Product Requirements Document: Shift Management Module

## 1. Introduction/Overview

This document describes the requirements for a **Shift Management Module** within the Production Entry App for ERPNext. The module introduces a **Shift** document that acts as a central hub for supervisors to manage shift-related information, including planned losses, warehouse defaults, and downtime tracking.

### Problem Statement

Currently, supervisors lack a streamlined way to manage shift information within ERPNext. Production entries, planned losses (breaks), and downtime are tracked separately without a unified context. This leads to:

- Difficulty in tracking shift-specific production data
- Manual calculation of planned vs actual work time
- No standardized way to associate downtime with specific shifts

### Solution

A dedicated Shift DocType that provides:

- Centralized shift information management
- Automatic calculation of planned losses based on shift duration
- Integration with existing Downtime Entry documents
- Default warehouse inheritance from Manufacturing Settings

---

## 2. Goals

1. **Simplify shift creation** - Supervisors can create a shift document with minimal input; defaults auto-populate
2. **Standardize planned losses** - Automatic population of break times based on shift duration
3. **Enable downtime association** - Link Downtime Entries to specific shifts for better tracking
4. **Maintain data integrity** - Prevent overlapping shifts and duplicate shift labels per date
5. **Support mobile usage** - Ensure the shift document is usable on mobile devices

---

## 3. User Stories

### Supervisor (Manufacturing User)

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-01 | Supervisor | Create a new shift with my current date/time pre-filled | I can quickly start documenting my shift |
| US-02 | Supervisor | Have planned breaks auto-populated based on shift duration | I don't have to manually enter standard break times |
| US-03 | Supervisor | Modify warehouse defaults for my shift | I can override settings when production moves to different areas |
| US-04 | Supervisor | Start and end my shift with button clicks | State transitions are clear and simple |
| US-05 | Supervisor | See all downtime events linked to my shift | I have a complete picture of shift interruptions |
| US-06 | Supervisor | Edit planned losses before starting the shift | I can adjust for non-standard break schedules |
| US-07 | Supervisor | Create shifts on my mobile phone | I can manage shifts from the shop floor |

### Manufacturing Manager

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-08 | Manager | Configure default warehouses for all shifts | Supervisors have correct defaults without manual setup |
| US-09 | Manager | View all shifts across dates | I can monitor production coverage |
| US-10 | Manager | Ensure no overlapping shifts exist | Production tracking remains accurate |

---

## 4. Functional Requirements

### 4.1 Shift DocType

| ID | Requirement |
|----|-------------|
| FR-01 | The system must create a Shift DocType with the following core fields: Shift Label (Select: "Shift 1", "Shift 2"), Shift Duration (Select: 8, 10, 12 hours), Shift Date (Date), Shift End Date (Date, derived), Planned Start Time (Time), Planned End Time (Time, readonly/derived), Supervisor (Link to User) |
| FR-02 | The system must auto-populate Shift Date with the current date on new document creation |
| FR-03 | The system must auto-populate Planned Start Time with the current time on new document creation |
| FR-04 | The system must auto-capture the Supervisor field from the current logged-in user |
| FR-05 | The system must calculate Planned End Time as: Planned Start Time + Shift Duration |
| FR-06 | The system must automatically set Shift End Date to the next day when Planned End Time crosses midnight |
| FR-07 | The system must use the naming series format: `SHIFT-YYYY.MM.DD.Shift-{N}` |

### 4.2 Default Warehouses

| ID | Requirement |
|----|-------------|
| FR-08 | The Shift DocType must include warehouse fields: Raw Material Warehouse, Work In Progress Warehouse, Rejection Warehouse, Scrap Warehouse |
| FR-09 | On new Shift creation, warehouse fields must copy values from Manufacturing Settings |
| FR-10 | Supervisors must be able to modify warehouse values on draft shifts |

### 4.3 Loss Type Master

| ID | Requirement |
|----|-------------|
| FR-11 | The system must create a Loss Type DocType with fields: Loss Type Name (Data), Default Duration (Int, in minutes) |
| FR-12 | The system must include default Loss Type records via fixtures: "Tea Break" (15 minutes), "Lunch Break" (30 minutes) |

### 4.4 Planned Losses Child Table

| ID | Requirement |
|----|-------------|
| FR-13 | The Shift DocType must include a "Planned Losses" child table with fields: Loss Type (Link), Start Time (Time), End Time (Time) |
| FR-14 | When Shift Duration is set to 8 hours, the system must auto-populate: Tea Break at +2 hours (15 min), Lunch Break at +4 hours (30 min) |
| FR-15 | When Shift Duration is set to 10 or 12 hours, the system must auto-populate: Tea Break at +2 hours (15 min), Lunch Break at +4 hours (30 min), Tea Break at +6 hours (15 min) |
| FR-16 | Planned Losses must be editable in Draft state |
| FR-17 | Planned Losses must be locked (non-editable) in Running and Completed states |

### 4.5 Workflow & State Management

| ID | Requirement |
|----|-------------|
| FR-18 | The Shift DocType must support states: Draft, Running, Completed, Cancelled |
| FR-19 | The system must provide a "Start Shift" button visible only in Draft state |
| FR-20 | The system must provide an "End Shift" button visible only in Running state |
| FR-21 | The system must provide a "Cancel" action available only in Draft state |
| FR-22 | State transitions: Draft → Running (Start Shift), Running → Completed (End Shift), Draft → Cancelled (Cancel) |
| FR-23 | In Running state, Planned Losses must be locked; other fields may remain editable |
| FR-24 | In Completed and Cancelled states, the entire document must be locked |

### 4.6 Validation Rules

| ID | Requirement |
|----|-------------|
| FR-25 | The system must prevent saving/submitting shifts with overlapping time periods |
| FR-26 | The system must enforce unique Shift Label per date (only one "Shift 1" and one "Shift 2" per date globally) |
| FR-27 | The system must validate and prevent duplicate naming conflicts |

### 4.7 Downtime Entry Integration

| ID | Requirement |
|----|-------------|
| FR-28 | The system must add a custom "Shift" link field to the Downtime Entry DocType |
| FR-29 | The Shift link field on Downtime Entry must be optional |
| FR-30 | The Shift document must display linked Downtime Entries in a dedicated section |

### 4.8 Manufacturing Settings Customization

| ID | Requirement |
|----|-------------|
| FR-31 | The system must add a "Shift Settings" tab to Manufacturing Settings via custom fields |
| FR-32 | The Shift Settings tab must include: Raw Material Warehouse, Work In Progress Warehouse, Rejection Warehouse, Scrap Warehouse (all Link to Warehouse) |

### 4.9 Permissions

| ID | Requirement |
|----|-------------|
| FR-33 | Manufacturing User role must have Create, Read, Write, Delete permissions on Shift |
| FR-34 | Manufacturing Manager role must have Create, Read, Write, Delete permissions on Shift |

### 4.10 Notifications

| ID | Requirement |
|----|-------------|
| FR-35 | The system must send a notification when a shift is started (transitions to Running state) |
| FR-36 | The system must send a notification when a shift is ended (transitions to Completed state) |

### 4.11 Shift Conflict Warnings

| ID | Requirement |
|----|-------------|
| FR-37 | The system must display a warning if a supervisor attempts to start a new shift while another shift is currently in Running state |
| FR-38 | Shifts must NOT auto-complete when the planned end time passes; manual "End Shift" action is always required |

---

## 5. Non-Goals (Out of Scope)

The following features are explicitly excluded from this phase:

| ID | Excluded Feature | Reason |
|----|------------------|--------|
| NG-01 | Production Entry Link | Linking Stock Entry (Manufacture type) to Shift - Future phase |
| NG-02 | Actual Loss Tracking | Tracking actual vs planned loss durations - Future phase |
| NG-03 | Workstation Association | Linking shifts to specific workstations - Future phase |
| NG-04 | Custom Shift Labels | Adding more shift labels beyond "Shift 1" / "Shift 2" - Future phase |
| NG-05 | Custom Shift Durations | Adding durations beyond 8/10/12 hours - Future phase |

---

## 6. Design Considerations

### 6.1 UI/UX Requirements

- **Mobile-first design**: The Shift document must be fully functional on mobile devices
- **Touch-friendly**: Large touch targets for action buttons (Start Shift, End Shift)
- **Simplified layout**: Clear visual hierarchy with critical fields prominent
- **State indicators**: Visual cues for current shift state (Draft/Running/Completed)

### 6.2 Form Layout

1. **Header Section**: Shift Label, Shift Duration, Dates/Times
2. **Warehouses Section**: Collapsible section with 4 warehouse fields
3. **Planned Losses Section**: Child table with loss entries
4. **Downtime Section**: Read-only display of linked Downtime Entries
5. **Action Buttons**: Prominently displayed state transition buttons

---

## 7. Technical Considerations

### 7.1 DocTypes to Create

1. **Loss Type** - Master DocType for loss type definitions
2. **Shift Planned Loss** - Child table DocType for planned losses
3. **Shift** - Main document DocType

### 7.2 Custom Fields (Fixtures)

- **Manufacturing Settings**: 4 warehouse link fields in "Shift Settings" tab
- **Downtime Entry**: 1 "Shift" link field

### 7.3 Fixtures Required

- Custom Fields JSON for Manufacturing Settings
- Custom Fields JSON for Downtime Entry
- Default Loss Type records (Tea Break, Lunch Break)

### 7.4 Dependencies

- ERPNext Manufacturing module must be installed
- Manufacturing Settings must exist
- Downtime Entry DocType must exist

### 7.5 Framework Patterns

- Use `frappe.get_doc()` for document operations
- Use `frappe.throw()` with `_()` for user-facing validation errors
- Use `doc.flags` for temporary state management
- Follow Frappe naming conventions for DocTypes and fields

---

## 8. Success Metrics

Based on the acceptance criteria from the specification:

| ID | Metric | Validation Method |
|----|--------|-------------------|
| SM-01 | Supervisor can create a new Shift document with default values populated | Manual testing |
| SM-02 | Planned losses auto-populate based on selected shift duration | Unit tests + Manual testing |
| SM-03 | Warehouses copy from Manufacturing Settings on new shift creation | Unit tests |
| SM-04 | Shift transitions through Draft → Running → Completed states correctly | Workflow tests |
| SM-05 | Planned losses lock when shift moves to Running state | UI + Backend tests |
| SM-06 | System prevents overlapping shifts | Validation tests |
| SM-07 | System enforces unique shift label per date | Validation tests |
| SM-08 | Downtime Entries can optionally link to a Shift | Integration tests |
| SM-09 | Shift document is usable on mobile devices | Manual UI testing |
| SM-10 | Midnight-crossing shifts correctly calculate end date | Unit tests |

---

## 9. Open Questions

| ID | Question | Decision | Action |
|----|----------|----------|--------|
| OQ-01 | Should there be notifications when a shift is started/ended? | Yes | Added FR-35, FR-36 |
| OQ-02 | Should shifts auto-complete if end time passes without manual completion? | No | Added FR-38 (explicit no auto-complete) |
| OQ-03 | Is there a need for shift handover notes between Shift 1 and Shift 2? | Future consideration | Deferred to future phase |
| OQ-04 | Should the system warn if a supervisor tries to start a new shift while another is running? | Yes | Added FR-37 |

---

## Appendix: Data Models

### Loss Type

```
Loss Type
├── loss_type_name (Data, required)
└── default_duration (Int, minutes)
```

### Shift Planned Loss (Child Table)

```
Shift Planned Loss
├── loss_type (Link: Loss Type)
├── start_time (Time)
└── end_time (Time)
```

### Shift

```
Shift
├── shift_label (Select: "Shift 1", "Shift 2")
├── shift_duration (Select: 8, 10, 12)
├── shift_date (Date)
├── shift_end_date (Date, derived)
├── planned_start_time (Time)
├── planned_end_time (Time, readonly)
├── supervisor (Link: User)
├── raw_material_warehouse (Link: Warehouse)
├── work_in_progress_warehouse (Link: Warehouse)
├── rejection_warehouse (Link: Warehouse)
├── scrap_warehouse (Link: Warehouse)
├── planned_losses (Table: Shift Planned Loss)
└── status (Select: Draft, Running, Completed, Cancelled)
```
