from __future__ import annotations

import json
from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.overrides import stock_entry_hooks
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	bootstrap_manufacture_masters,
	make_completed_shift,
	make_direct_manufacture_entry,
	make_running_shift,
)
from production_entry_app.production_entry_app.utils.alternative_items import (
	get_bom_alternative_allowed_items,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	cleanup_running_shifts,
	ensure_department,
	ensure_item,
	ensure_operator,
	ensure_production_entry_settings_shift_fields,
	ensure_warehouse,
	ensure_workstation,
	get_company_abbr,
	resolve_test_company,
)


def _ensure_downtime_reasons() -> None:
	"""Ensure Tea Break and Lunch Break Downtime Reasons exist."""
	for name in ("Tea Break", "Lunch Break", "Setup Time", "Maint"):
		if not frappe.db.exists("Downtime Reason", name):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()


def _ensure_rejection_breakup_doctype() -> None:
	if not frappe.db.exists("DocType", "Rejection Breakup"):
		frappe.reload_doc("production_entry_app", "doctype", "rejection_breakup")
		frappe.clear_cache(doctype="Rejection Breakup")
		return
	if not frappe.get_meta("Rejection Breakup", cached=True).has_field("is_rework"):
		frappe.reload_doc("production_entry_app", "doctype", "rejection_breakup")
		frappe.clear_cache(doctype="Rejection Breakup")


def _ensure_rejection_reason_doctype() -> None:
	if not frappe.db.exists("DocType", "Rejection Reason"):
		frappe.reload_doc("production_entry_app", "doctype", "rejection_reason")


def _ensure_rejection_reasons() -> None:
	for name in ("Burr", "Crack"):
		if not frappe.db.exists("Rejection Reason", name):
			frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": name}).insert()


def _ensure_rejection_breakup_custom_field() -> None:
	if frappe.db.exists("Custom Field", "Stock Entry-custom_pea_rejection_breakup"):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": "custom_pea_rejection_breakup",
			"fieldtype": "Table",
			"label": "Rejection Breakup",
			"options": "Rejection Breakup",
			"insert_after": "custom_pea_fetch_items",
			"depends_on": "eval:doc.custom_pea_rejection_qty > 0",
			"mandatory_depends_on": "eval:doc.custom_pea_rejection_qty > 0",
			"module": "Production Entry App",
		}
	).insert(ignore_permissions=True)


def _ensure_die_tool_maintenance_log_doctype() -> None:
	if not frappe.db.exists("DocType", "Die Tool Maintenance Log"):
		frappe.reload_doc("production_entry_app", "doctype", "die_tool_maintenance_log")


def _ensure_die_tool_counter_doctype() -> None:
	if not frappe.db.exists("DocType", "Die Tool Counter"):
		frappe.reload_doc("production_entry_app", "doctype", "die_tool_counter")


def _ensure_loss_entry_shift_field() -> None:
	if frappe.get_meta("Loss Entry", cached=True).has_field("shift"):
		return
	frappe.reload_doc("production_entry_app", "doctype", "loss_entry")
	frappe.clear_cache(doctype="Loss Entry")


def _ensure_item_die_tool_fields() -> None:
	created = False
	if not frappe.db.exists("Custom Field", "Item-custom_pea_strokes_per_unit"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Item",
				"fieldname": "custom_pea_strokes_per_unit",
				"fieldtype": "Float",
				"label": "Strokes Per Unit",
				"insert_after": "item_name",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)
		created = True

	if not frappe.db.exists("Custom Field", "Item-custom_pea_stroke_capacity"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Item",
				"fieldname": "custom_pea_stroke_capacity",
				"fieldtype": "Float",
				"label": "Max Stroke Count",
				"insert_after": "custom_pea_strokes_per_unit",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)
		created = True

	if not frappe.db.exists("Custom Field", "Item-custom_pea_has_die_tool"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Item",
				"fieldname": "custom_pea_has_die_tool",
				"fieldtype": "Check",
				"label": "Has Die Tool",
				"default": "1",
				"insert_after": "custom_pea_stroke_capacity",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)
		created = True

	if created:
		frappe.reload_doc("core", "doctype", "item")
		frappe.db.updatedb("Item")


class TestStockEntryHookPureHelpers(FrappeTestCase):
	def test_on_trash_stock_entry_deletes_loss_rows_for_parent(self) -> None:
		doc = frappe._dict({"name": "MAT-STE-UNIT-001"})
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.delete"
		) as delete:
			stock_entry_hooks.on_trash_stock_entry(doc)
		delete.assert_called_once_with(
			"Loss Entry",
			{"parenttype": "Stock Entry", "parent": "MAT-STE-UNIT-001"},
		)

	def test_validate_linked_shift_can_accept_stock_entry_returns_when_shift_missing(self) -> None:
		stock_entry_hooks._validate_linked_shift_can_accept_stock_entry(frappe._dict({}))

	def test_get_shift_buffer_minutes_clamps_default_when_settings_field_missing(self) -> None:
		meta = type("Meta", (), {"has_field": lambda self, fieldname: False})()
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta",
			return_value=meta,
		):
			self.assertEqual(stock_entry_hooks._get_shift_buffer_minutes("shift_start_buffer_mins", -1), 0)
			self.assertEqual(stock_entry_hooks._get_shift_buffer_minutes("shift_end_buffer_mins", 999), 480)

	def test_find_overlapping_downtime_entry_returns_none_when_inputs_missing(self) -> None:
		self.assertIsNone(stock_entry_hooks._find_overlapping_downtime_entry("", None, None))

	def test_validate_rejection_breakup_rejects_zero_quantity_row(self) -> None:
		doc = frappe._dict(
			{
				"custom_pea_rejection_qty": 1,
				"custom_pea_rejection_breakup": [
					frappe._dict({"rejection_reason": "Burr", "qty": 0, "is_rework": 0})
				],
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "quantity greater than 0"):
			stock_entry_hooks._validate_rejection_breakup(doc)

	def test_direct_manufacture_validation_skips_v16_legacy_scrap_rows(self) -> None:
		row = frappe._dict({"idx": 3, "item_code": "MSScrap", "is_legacy_scrap_item": 1})

		stock_entry_hooks._validate_direct_manufacture_alternative_row(
			row,
			"BOM-FG001-001",
			{"RM001"},
			set(),
		)

	def test_direct_manufacture_validation_skips_bom_secondary_item_rows(self) -> None:
		row = frappe._dict({"idx": 3, "item_code": "MSScrap"})

		stock_entry_hooks._validate_direct_manufacture_alternative_row(
			row,
			"BOM-FG002SHR-002",
			{"RM001"},
			set(),
			{"MSScrap"},
		)

	def test_direct_manufacture_validation_uses_bom_secondary_item_query(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"from_bom": 1,
				"bom_no": "BOM-FG002SHR-005",
				"items": [frappe._dict({"idx": 3, "item_code": "MSScrap"})],
			}
		)

		with (
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.get_bom_item_codes",
				return_value={"RM001"},
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.get_bom_alternative_allowed_items",
				return_value=set(),
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks._get_bom_secondary_item_codes",
				return_value={"MSScrap"},
			) as get_secondary_items,
		):
			stock_entry_hooks._validate_direct_manufacture_alternative_items(doc)

		get_secondary_items.assert_called_once_with("BOM-FG002SHR-005")

	def test_direct_manufacture_validation_marks_alternative_allowed_rows(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"from_bom": 1,
				"bom_no": "BOM-FG002SHR-005",
				"items": [
					frappe._dict({"item_code": "RM001", "allow_alternative_item": 0}),
					frappe._dict({"item_code": "FG002SHR", "is_finished_item": 1}),
				],
			}
		)

		with (
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_alternative_allowed_items",
				return_value={"RM001"},
			),
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_secondary_item_codes",
				return_value=set(),
			),
		):
			stock_entry_hooks._set_direct_manufacture_alternative_flags(doc)

		self.assertEqual(doc["items"][0].allow_alternative_item, 1)
		self.assertFalse(doc["items"][1].get("allow_alternative_item"))

	def test_direct_manufacture_validation_flags_skip_legacy_scrap_and_secondary_rows(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"from_bom": 1,
				"bom_no": "BOM-FG002SHR-005",
				"items": [
					frappe._dict({"item_code": "RM001", "allow_alternative_item": 0}),
					frappe._dict({"item_code": "LEGACY-SCRAP", "is_legacy_scrap_item": 1}),
					frappe._dict({"item_code": "SECONDARY-OUTPUT"}),
				],
			}
		)

		with (
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_alternative_allowed_items",
				return_value={"RM001", "LEGACY-SCRAP", "SECONDARY-OUTPUT"},
			),
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_secondary_item_codes",
				return_value={"SECONDARY-OUTPUT"},
			),
		):
			stock_entry_hooks._set_direct_manufacture_alternative_flags(doc)

		self.assertEqual([row.get("allow_alternative_item") for row in doc["items"]], [1, None, None])

	def test_get_docfield_precision_defaults_when_field_missing(self) -> None:
		meta = type("Meta", (), {"get_field": lambda self, fieldname: None})()
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta",
			return_value=meta,
		):
			self.assertEqual(stock_entry_hooks._get_docfield_precision("Stock Entry", "missing", object()), 3)

	def test_validate_rejection_target_warehouses_returns_when_flag_missing_and_requires_target(self) -> None:
		doc = frappe._dict(
			{
				"items": [
					frappe._dict({"custom_pea_is_rejection_item": 1, "t_warehouse": ""}),
				]
			}
		)
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._has_rejected_warehouse_flag",
			return_value=False,
		):
			stock_entry_hooks._validate_rejection_target_warehouses(doc)
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._has_rejected_warehouse_flag",
			return_value=True,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Target Warehouse"):
				stock_entry_hooks._validate_rejection_target_warehouses(doc)

	def test_rejection_warehouse_uses_settings_fallback_and_throws_when_missing(self) -> None:
		doc = frappe._dict({"custom_pea_shift": ""})
		meta = type("Meta", (), {"has_field": lambda self, fieldname: True})()
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta",
			return_value=meta,
		):
			with patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.get_single_value",
				return_value="Rejected WH",
			):
				self.assertEqual(stock_entry_hooks._get_rejection_warehouse(doc), "Rejected WH")
			with patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.get_single_value",
				return_value=None,
			):
				with self.assertRaisesRegex(frappe.ValidationError, "Rejection Warehouse"):
					stock_entry_hooks._get_rejection_warehouse(doc)

	def test_existing_rejection_target_warehouse_ignores_invalid_new_doc_candidates(self) -> None:
		doc = frappe._dict(
			{
				"items": [
					frappe._dict({"custom_pea_is_rejection_item": 1, "t_warehouse": "Invalid WH", "idx": 1})
				],
				"is_new": lambda: True,
			}
		)
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._has_rejected_warehouse_flag",
			return_value=True,
		):
			with patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks._is_rejected_warehouse",
				return_value=False,
			):
				self.assertIsNone(stock_entry_hooks._get_existing_rejection_target_warehouse(doc))

	def test_build_metrics_note_handles_zero_partial_and_full_loss_windows(self) -> None:
		self.assertEqual(stock_entry_hooks._build_metrics_note(0, 1), "")
		self.assertEqual(stock_entry_hooks._build_metrics_note(10, 5), "")
		self.assertIn("deducted loss time", stock_entry_hooks._build_metrics_note(10, 10))

	def test_get_shift_planned_losses_for_metrics_returns_empty_when_shift_missing_or_incomplete(
		self,
	) -> None:
		self.assertEqual(
			stock_entry_hooks._get_shift_planned_losses_for_metrics(frappe._dict({})),
			([], None, None),
		)
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.get_value",
			return_value=None,
		):
			self.assertEqual(
				stock_entry_hooks._get_shift_planned_losses_for_metrics(
					frappe._dict({"custom_pea_shift": "SHIFT-001"})
				),
				([], None, None),
			)


def _ensure_stock_entry_metric_fields() -> None:
	metric_fields = [
		{
			"name": "Stock Entry-custom_pea_ok_qty",
			"fieldname": "custom_pea_ok_qty",
			"fieldtype": "Float",
			"label": "OK Qty",
			"insert_after": "bom_no",
		},
		{
			"name": "Stock Entry-custom_pea_rework_qty",
			"fieldname": "custom_pea_rework_qty",
			"fieldtype": "Float",
			"label": "Rework Quantity",
			"insert_after": "custom_pea_ok_qty",
		},
		{
			"name": "Stock Entry-custom_pea_actual_duration_mins",
			"fieldname": "custom_pea_actual_duration_mins",
			"fieldtype": "Float",
			"label": "Actual Duration (Minutes)",
			"insert_after": "custom_pea_rejection_breakup",
		},
		{
			"name": "Stock Entry-custom_pea_production_time_mins",
			"fieldname": "custom_pea_production_time_mins",
			"fieldtype": "Float",
			"label": "Production Time (Minutes)",
			"insert_after": "custom_pea_actual_duration_mins",
		},
		{
			"name": "Stock Entry-custom_pea_actual_spm",
			"fieldname": "custom_pea_actual_spm",
			"fieldtype": "Float",
			"label": "Actual SPM",
			"insert_after": "custom_pea_production_time_mins",
		},
		{
			"name": "Stock Entry-custom_pea_cycle_time_sec",
			"fieldname": "custom_pea_cycle_time_sec",
			"fieldtype": "Float",
			"label": "Cycle Time (sec/unit)",
			"insert_after": "custom_pea_actual_spm",
		},
		{
			"name": "Stock Entry-custom_pea_operator_efficiency_pct",
			"fieldname": "custom_pea_operator_efficiency_pct",
			"fieldtype": "Float",
			"label": "Operator Efficiency (%)",
			"read_only": 1,
			"insert_after": "custom_pea_cycle_time_sec",
		},
		{
			"name": "Stock Entry-custom_pea_metrics_note",
			"fieldname": "custom_pea_metrics_note",
			"fieldtype": "Small Text",
			"label": "Metrics Note",
			"read_only": 1,
			"insert_after": "custom_pea_operator_efficiency_pct",
		},
		{
			"name": "Stock Entry-custom_pea_die_tool_utilization_pct",
			"fieldname": "custom_pea_die_tool_utilization_pct",
			"fieldtype": "Float",
			"label": "Die Tool Utilization (%)",
			"read_only": 1,
			"insert_after": "custom_pea_metrics_note",
		},
		{
			"name": "Stock Entry-custom_pea_die_tool_maintenance_due",
			"fieldname": "custom_pea_die_tool_maintenance_due",
			"fieldtype": "Check",
			"label": "Die Tool Maintenance Due",
			"insert_after": "custom_pea_die_tool_utilization_pct",
		},
	]

	created = False
	for field in metric_fields:
		if frappe.db.exists("Custom Field", field["name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Stock Entry",
				"module": "Production Entry App",
				"read_only": 1,
				**field,
			}
		).insert(ignore_permissions=True)
		created = True

	if created:
		frappe.reload_doc("stock", "doctype", "stock_entry")
		frappe.db.updatedb("Stock Entry")


def _append_rejection_breakup_rows(doc, rows: list[dict]) -> None:
	for row in rows:
		doc.append("custom_pea_rejection_breakup", row)


def _get_or_create_warehouse(name: str, company: str) -> str:
	return ensure_warehouse(name, company)


def _get_or_create_item(item_code: str) -> str:
	return ensure_item(item_code)


def _set_item_die_tool_fields(
	item_code: str, strokes_per_unit: float, stroke_capacity: float, has_die_tool: int = 1
) -> None:
	frappe.db.set_value("Item", item_code, "custom_pea_strokes_per_unit", strokes_per_unit)
	frappe.db.set_value("Item", item_code, "custom_pea_stroke_capacity", stroke_capacity)
	frappe.db.set_value("Item", item_code, "custom_pea_has_die_tool", has_die_tool)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure custom fields are persisted


def _create_test_shift(
	shift_date: str = "2026-04-10",
	shift_label: str = "1",
	planned_start_time: str = "08:00:00",
	branch: str | None = None,
	wip_warehouse: str | None = None,
	rejection_warehouse: str | None = None,
) -> frappe.Document:
	"""Create and return a test Shift."""
	_ensure_downtime_reasons()
	cleanup_running_shifts()
	department = ensure_department("Test Department")
	for existing_name in frappe.get_all(
		"Shift",
		filters={"department": department, "shift_date": shift_date, "shift_label": shift_label},
		pluck="name",
	):
		frappe.delete_doc("Shift", existing_name, force=True, ignore_permissions=True)

	doc_data = {
		"doctype": "Shift",
		"department": department,
		"shift_label": shift_label,
		"shift_duration": "8",
		"shift_date": shift_date,
		"planned_start_time": planned_start_time,
	}
	if branch:
		doc_data["branch"] = branch
	if wip_warehouse:
		doc_data["work_in_progress_warehouse"] = wip_warehouse
	if rejection_warehouse:
		doc_data["rejection_warehouse"] = rejection_warehouse

	shift = frappe.get_doc(doc_data).insert()
	# Start the shift so Stock Entry can link it.
	shift.start_shift()
	return shift


def _get_or_create_bom(
	fg_item: str,
	rm_item: str,
	company: str,
	rm_qty: float = 1,
	allow_alternative_item: int = 0,
) -> str:
	"""Return BOM name for fg_item, creating and submitting one if needed."""
	bom_names = frappe.get_all(
		"BOM",
		filters={
			"item": fg_item,
			"company": company,
			"is_active": 1,
			"is_default": 1,
			"docstatus": 1,
		},
		pluck="name",
	)
	if bom_names:
		matching_items = frappe.get_all(
			"BOM Item",
			filters={
				"parent": ["in", bom_names],
				"parenttype": "BOM",
				"item_code": rm_item,
				"qty": rm_qty,
				"allow_alternative_item": allow_alternative_item,
			},
			fields=["parent"],
			limit=1,
		)
		if matching_items:
			return matching_items[0].parent

	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": fg_item,
			"company": company,
			"quantity": 1,
			"is_active": 1,
			"is_default": 1,
			"items": [
				{
					"item_code": rm_item,
					"qty": rm_qty,
					"rate": 50,
					"allow_alternative_item": allow_alternative_item,
				}
			],
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def _create_bom_stock_entry(
	company: str,
	bom_no: str,
	fg_completed_qty: float = 100,
	custom_pea_rejection_qty: float = 0,
	custom_pea_shift: str | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
) -> frappe.Document:
	"""Create a Manufacture Stock Entry with from_bom=1 and call get_items()."""
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": company,
			"from_bom": 1,
			"bom_no": bom_no,
			"fg_completed_qty": fg_completed_qty,
			"custom_pea_rejection_qty": custom_pea_rejection_qty,
			"posting_date": frappe.utils.nowdate(),
			"posting_time": frappe.utils.nowtime(),
		}
	)
	if custom_pea_shift:
		se.custom_pea_shift = custom_pea_shift
	if from_warehouse:
		se.from_warehouse = from_warehouse
	if to_warehouse:
		se.to_warehouse = to_warehouse
	se.get_items()
	return se


def _create_manufacture_stock_entry(
	company: str,
	fg_item: str,
	rm_item: str,
	fg_qty: float = 100,
	rm_qty: float = 100,
	custom_pea_shift: str | None = None,
	custom_pea_rejection_qty: float = 0,
	fg_warehouse: str | None = None,
	rm_warehouse: str | None = None,
) -> frappe.Document:
	"""Create a Manufacture Stock Entry with raw material and finished good rows."""
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": company,
			"fg_completed_qty": fg_qty,
		}
	)

	if custom_pea_shift:
		se.custom_pea_shift = custom_pea_shift
	if custom_pea_rejection_qty:
		se.custom_pea_rejection_qty = custom_pea_rejection_qty

	# Raw material row
	se.append(
		"items",
		{
			"item_code": rm_item,
			"qty": rm_qty,
			"basic_rate": 50,
			"s_warehouse": rm_warehouse,
		},
	)

	# Finished good row
	se.append(
		"items",
		{
			"item_code": fg_item,
			"qty": fg_qty,
			"t_warehouse": fg_warehouse,
			"is_finished_item": 1,
		},
	)

	return se


def _set_shift_buffers(start_mins: int = 60, end_mins: int = 60) -> None:
	ensure_production_entry_settings_shift_fields()
	frappe.db.set_single_value("Production Entry Settings", "shift_start_buffer_mins", start_mins)
	frappe.db.set_single_value("Production Entry Settings", "shift_end_buffer_mins", end_mins)


def _get_or_create_employee(employee_number: str = "SE-HOOK-EMP") -> str:
	employee_name = frappe.db.get_value("Employee", {"employee_number": employee_number}, "name")
	if employee_name:
		return employee_name

	company = resolve_test_company()
	return (
		frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "SE",
				"last_name": "Hook",
				"gender": "Female",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"company": company,
				"status": "Active",
				"employee_number": employee_number,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _create_downtime_entry(workstation: str, operator: str, from_time: str, to_time: str) -> frappe.Document:
	return frappe.get_doc(
		{
			"doctype": "Downtime Entry",
			"workstation": workstation,
			"operator": operator,
			"from_time": from_time,
			"to_time": to_time,
			"stop_reason": "Other",
		}
	).insert(ignore_permissions=True)


class TestStockEntryHooks(FrappeTestCase):
	# Shift dates used by tests in this class (April 10-17, 2026)
	_SHIFT_DATES: ClassVar[list[str]] = [f"2026-04-{d}" for d in range(10, 18)]

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_loss_entry_shift_field()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_stock_entry_metric_fields()
		context = bootstrap_manufacturing_test_context("SE Hook")
		cls.company = context["company"]
		cls.wip_warehouse = context["wip_warehouse"]
		cls.rm_warehouse = context["rm_warehouse"]
		cls.rejection_warehouse = context["rejection_warehouse"]
		cls.fg_warehouse = context["fg_warehouse"]
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")

	def setUp(self) -> None:
		cleanup_running_shifts()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure running shift cleanup is visible
		_ensure_loss_entry_shift_field()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_stock_entry_metric_fields()
		context = bootstrap_manufacturing_test_context("SE Hook")
		self.company = context["company"]
		self.wip_warehouse = context["wip_warehouse"]
		self.rm_warehouse = context["rm_warehouse"]
		self.rejection_warehouse = context["rejection_warehouse"]
		self.fg_warehouse = context["fg_warehouse"]
		self.fg_item = _get_or_create_item("_Test FG Item For Shift")
		self.rm_item = _get_or_create_item("_Test RM Item For Shift")

	def tearDown(self) -> None:
		frappe.db.rollback()

	@classmethod
	def tearDownClass(cls) -> None:
		"""End all Running shifts created by this test class to prevent leakage."""
		department = ensure_department("Test Department")
		for shift_date in cls._SHIFT_DATES:
			for label in ("1", "2"):
				for name in frappe.get_all(
					"Shift",
					filters={"department": department, "shift_date": shift_date, "shift_label": label},
					pluck="name",
				):
					frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed to persist cleanup
		super().tearDownClass()

	def test_shift_reference_auto_fills_branch(self) -> None:
		if not frappe.db.exists("Branch", "Test Branch SE"):
			frappe.get_doc({"doctype": "Branch", "branch": "Test Branch SE"}).insert(ignore_permissions=True)

		shift = _create_test_shift(
			shift_date="2026-04-10",
			branch="Test Branch SE",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertEqual(se.branch, "Test Branch SE")

	def test_shift_reference_auto_fills_planned_dates(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-11",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-11", str(se.custom_pea_planned_start_date))
		self.assertIn("08:00:00", str(se.custom_pea_planned_start_date))
		self.assertIn("16:00:00", str(se.custom_pea_planned_end_date))

	def test_rejection_breakup_required_when_rejection_qty_positive(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_total_exceeds_rejection_qty_throws(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 3, "remark": "Surface crack"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_total_less_than_rejection_qty_throws(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 1, "remark": "Surface crack"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_reason_required(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(se, [{"qty": 5, "remark": "Missing reason"}])

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_valid_allows_save(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)

		se.save()

		self.assertEqual(len(se.custom_pea_rejection_breakup), 2)

	def test_rework_qty_is_computed_from_rework_rows(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-17",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "is_rework": 1},
				{"rejection_reason": "Crack", "qty": 2, "is_rework": 0},
			],
		)

		se.save()
		self.assertEqual(float(se.custom_pea_rework_qty or 0), 3.0)

	def test_rejection_breakup_allows_difference_within_precision_tolerance(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_get_rejection_breakup_abs_tol,
		)

		shift = _create_test_shift(
			shift_date="2026-04-17",
			shift_label="2",
			planned_start_time="17:00:00",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		abs_tol = _get_rejection_breakup_abs_tol(se, [frappe._dict(qty=5)])
		within_delta = abs_tol * 0.9
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 5 + within_delta, "remark": "Within precision tolerance"},
			],
		)

		se.save()

	def test_rejection_breakup_rejects_difference_beyond_precision_tolerance(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_get_rejection_breakup_abs_tol,
		)

		shift = _create_test_shift(
			shift_date="2026-04-20",
			shift_label="2",
			planned_start_time="17:00:00",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		abs_tol = _get_rejection_breakup_abs_tol(se, [frappe._dict(qty=5)])
		beyond_delta = abs_tol * 1.1
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 5 - beyond_delta, "remark": "Beyond precision tolerance"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rework_qty_is_zero_when_no_rows_marked_rework(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-18",
			shift_label="2",
			planned_start_time="17:00:00",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=4,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 0},
				{"rejection_reason": "Crack", "qty": 2, "is_rework": 0},
			],
		)

		se.save()
		self.assertEqual(float(se.custom_pea_rework_qty or 0), 0.0)

	def test_rework_qty_resets_to_zero_when_rejection_qty_zero(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-19",
			shift_label="2",
			planned_start_time="17:00:00",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=4,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 2, "is_rework": 1},
				{"rejection_reason": "Crack", "qty": 2, "is_rework": 1},
			],
		)
		se.save()
		self.assertEqual(float(se.custom_pea_rework_qty or 0), 4.0)

		se.custom_pea_rejection_qty = 0
		se.custom_pea_rejection_breakup = []
		se.save()
		self.assertEqual(float(se.custom_pea_rework_qty or 0), 0.0)

	def test_actual_times_within_buffer_pass(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-12 07:30:00"
		se.custom_pea_actual_end_date = "2026-04-12 16:30:00"
		se.save()

		self.assertEqual(str(se.custom_pea_actual_start_date), "2026-04-12 07:30:00")
		self.assertEqual(str(se.custom_pea_actual_end_date), "2026-04-12 16:30:00")

	def test_actual_start_before_allowed_range_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-13 06:59:00"
		se.custom_pea_actual_end_date = "2026-04-13 16:00:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_actual_end_after_allowed_range_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-14 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-14 17:01:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_actual_end_before_start_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-15 09:00:00"
		se.custom_pea_actual_end_date = "2026-04-15 08:59:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_shift_start_buffer_clamps_negative_to_zero(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_get_shift_buffer_minutes,
		)

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta"
		) as get_meta:
			get_meta.return_value.has_field.return_value = True
			with patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.get_single_value",
				return_value=-12,
			) as get_single_value:
				with patch(
					"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.log_error"
				) as log_error:
					value = _get_shift_buffer_minutes("shift_start_buffer_mins", 60)
		self.assertEqual(value, 0)
		get_meta.assert_called_once_with("Production Entry Settings", cached=True)
		get_single_value.assert_called_once_with("Production Entry Settings", "shift_start_buffer_mins")
		log_error.assert_called_once()

	def test_shift_end_buffer_clamps_overflow_to_max(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_MAX_BUFFER_MINS,
			_get_shift_buffer_minutes,
		)

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.get_meta"
		) as get_meta:
			get_meta.return_value.has_field.return_value = True
			with patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.db.get_single_value",
				return_value=9999,
			) as get_single_value:
				with patch(
					"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.log_error"
				) as log_error:
					value = _get_shift_buffer_minutes("shift_end_buffer_mins", 60)
		self.assertEqual(value, _MAX_BUFFER_MINS)
		get_meta.assert_called_once_with("Production Entry Settings", cached=True)
		get_single_value.assert_called_once_with("Production Entry Settings", "shift_end_buffer_mins")
		log_error.assert_called_once()

	def test_metrics_calculated_from_actual_times_and_output(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_standard_spm = 1
		se.custom_pea_actual_start_date = "2026-04-16 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-16 09:40:00"
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)

		se.save()

		expected_ok_qty = max(
			float(se.get("fg_completed_qty") or 0) - float(se.get("custom_pea_rejection_qty") or 0),
			0,
		)
		total_strokes = float(se.get("fg_completed_qty") or 0)
		self.assertEqual(float(se.custom_pea_ok_qty), expected_ok_qty)
		self.assertEqual(float(se.custom_pea_actual_duration_mins), 100.0)
		# Planned losses overlapping 08:00-09:40: Shift Start Up (10) + Tea Break (10) = 20 min.
		# JH Activity (10:00-10:10) is outside the entry window.
		self.assertEqual(float(se.custom_pea_production_time_mins), 80.0)
		self.assertAlmostEqual(
			float(se.custom_pea_actual_spm),
			float(total_strokes / 80.0 if total_strokes > 0 else 0),
			places=3,
		)
		self.assertAlmostEqual(
			float(se.custom_pea_cycle_time_sec),
			float((4800.0 / total_strokes) if total_strokes > 0 else 0),
			places=3,
		)
		self.assertAlmostEqual(
			float(se.custom_pea_operator_efficiency_pct), float((total_strokes / 80.0) * 100), places=2
		)
		self.assertNotIsInstance(se.get("custom_pea_actual_spm"), str)
		self.assertNotIsInstance(se.get("custom_pea_operator_efficiency_pct"), str)

	def test_metrics_use_production_time_after_setup_and_loss(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=120,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=20,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_standard_spm = 2
		se.custom_pea_actual_start_date = "2026-04-16 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-16 09:00:00"
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 12, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 8, "remark": "Surface crack"},
			],
		)
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Setup Time",
				"start_time": "08:00:00",
				"end_time": "08:20:00",
				"remark": "setup",
				"shift": shift.name,
			},
		)
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Maint",
				"start_time": "08:20:00",
				"end_time": "08:30:00",
				"remark": "maint",
				"shift": shift.name,
			},
		)

		se.save()

		# Wall-clock duration remains 60 mins, but production time is 30 mins after losses.
		total_strokes = float(se.get("fg_completed_qty") or 0)
		ok_qty = max(total_strokes - float(se.get("custom_pea_rejection_qty") or 0), 0)
		expected_spm = (total_strokes / 30.0) if total_strokes > 0 else 0.0
		expected_cycle_time = (1800.0 / total_strokes) if total_strokes > 0 else 0.0
		self.assertEqual(float(se.custom_pea_actual_duration_mins), 60.0)
		self.assertEqual(float(se.custom_pea_production_time_mins), 30.0)
		self.assertEqual(float(se.custom_pea_ok_qty), ok_qty)
		self.assertAlmostEqual(float(se.custom_pea_actual_spm), expected_spm, places=3)
		self.assertAlmostEqual(float(se.custom_pea_cycle_time_sec), expected_cycle_time, places=3)
		self.assertAlmostEqual(
			float(se.custom_pea_operator_efficiency_pct), float(expected_spm * 50.0), places=2
		)
		if total_strokes != ok_qty and ok_qty > 0:
			self.assertNotAlmostEqual(float(se.custom_pea_actual_spm), float(ok_qty / 30.0), places=3)

	def test_metrics_deduct_shift_planned_break_overlap(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=30,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_standard_spm = 1
		se.custom_pea_actual_start_date = "2026-04-16 08:50:00"
		se.custom_pea_actual_end_date = "2026-04-16 09:20:00"
		se.save()

		self.assertEqual(float(se.custom_pea_actual_duration_mins), 30.0)
		# Shift has Tea Break 09:00-09:10; overlap should be auto-deducted.
		self.assertEqual(float(se.custom_pea_production_time_mins), 20.0)

	def test_metrics_deduplicate_overlapping_planned_and_unplanned_breaks(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=30,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_standard_spm = 1
		se.custom_pea_actual_start_date = "2026-04-16 08:50:00"
		se.custom_pea_actual_end_date = "2026-04-16 09:20:00"
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Tea Break",
				"start_time": "09:00:00",
				"end_time": "09:10:00",
				"remark": "duplicate planned break",
				"shift": shift.name,
			},
		)
		se.save()

		self.assertEqual(float(se.custom_pea_actual_duration_mins), 30.0)
		# Planned + unplanned overlap the same interval; subtract once (10 mins), not twice.
		self.assertEqual(float(se.custom_pea_production_time_mins), 20.0)
		self.assertFalse(se.get("custom_pea_metrics_note"))

	def test_metrics_note_explains_when_deducted_losses_consume_full_window(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=120,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_standard_spm = 2
		se.custom_pea_actual_start_date = "2026-04-16 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-16 08:20:00"
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Setup Time",
				"start_time": "08:00:00",
				"end_time": "08:10:00",
				"remark": "setup",
				"shift": shift.name,
			},
		)
		se.save()

		self.assertEqual(float(se.custom_pea_actual_duration_mins), 20.0)
		# Planned: Shift Start Up 08:00-08:10. Unplanned: setup 08:00-08:10.
		# Merged = 10 min deducted. JH Activity (10:00-10:10) outside window.
		self.assertEqual(float(se.custom_pea_production_time_mins), 10.0)
		total_strokes = float(se.get("fg_completed_qty") or 0)
		self.assertAlmostEqual(
			float(se.custom_pea_actual_spm),
			float(total_strokes / 10.0 if total_strokes > 0 else 0),
			places=3,
		)
		self.assertAlmostEqual(
			float(se.custom_pea_operator_efficiency_pct),
			float(
				(total_strokes / (10.0 * se.custom_pea_standard_spm)) * 100
				if se.custom_pea_standard_spm
				else 0
			),
			places=2,
		)
		self.assertFalse(se.get("custom_pea_metrics_note"))

	def test_metrics_remain_empty_when_actual_times_missing(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-17",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=50,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-17 08:00:00"
		se.custom_pea_actual_end_date = None
		se.save()

		self.assertFalse(se.get("custom_pea_actual_duration_mins"))
		self.assertFalse(se.get("custom_pea_production_time_mins"))
		self.assertFalse(se.get("custom_pea_actual_spm"))
		self.assertFalse(se.get("custom_pea_cycle_time_sec"))
		self.assertFalse(se.get("custom_pea_operator_efficiency_pct"))

	def test_metrics_zero_duration_clears_metric_fields(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=50,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-18 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-18 08:00:00"
		se.save()

		self.assertFalse(se.get("custom_pea_actual_duration_mins"))
		self.assertFalse(se.get("custom_pea_production_time_mins"))
		self.assertFalse(se.get("custom_pea_actual_spm"))
		self.assertFalse(se.get("custom_pea_cycle_time_sec"))
		self.assertFalse(se.get("custom_pea_operator_efficiency_pct"))

	def test_rejection_row_copies_project_from_fg_row(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		project_name = f"_Test Project PEA {frappe.generate_hash(length=6)}"
		project_doc_name = (
			frappe.get_doc({"doctype": "Project", "project_name": project_name, "company": self.company})
			.insert(ignore_permissions=True)
			.name
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		for row in se.items:
			if row.is_finished_item:
				row.project = project_doc_name
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)
		se.save()

		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].project, project_doc_name)

	def test_shift_defaults_warehouses_from_production_entry_settings(self) -> None:
		scrap_warehouse = _get_or_create_warehouse("SE Hook Scrap Warehouse", self.company)
		ensure_production_entry_settings_shift_fields()
		frappe.db.set_single_value(
			"Production Entry Settings", "shift_raw_material_warehouse", self.rm_warehouse
		)
		frappe.db.set_single_value("Production Entry Settings", "shift_wip_warehouse", self.wip_warehouse)
		frappe.db.set_single_value(
			"Production Entry Settings", "shift_rejection_warehouse", self.rejection_warehouse
		)
		frappe.db.set_single_value("Production Entry Settings", "shift_scrap_warehouse", scrap_warehouse)

		shift = _create_test_shift(shift_date="2026-04-18", wip_warehouse=None, rejection_warehouse=None)

		self.assertEqual(shift.raw_material_warehouse, self.rm_warehouse)
		self.assertEqual(shift.work_in_progress_warehouse, self.wip_warehouse)
		self.assertEqual(shift.rejection_warehouse, self.rejection_warehouse)
		self.assertEqual(shift.scrap_warehouse, scrap_warehouse)

	def test_rejection_warehouse_uses_production_entry_settings_fallback(self) -> None:
		ensure_production_entry_settings_shift_fields()
		frappe.db.set_single_value(
			"Production Entry Settings", "shift_rejection_warehouse", self.rejection_warehouse
		)
		shift = _create_test_shift(
			shift_date="2026-04-19",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=None,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 5, "remark": "Fallback WH"},
			],
		)
		se.save()

		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].t_warehouse, self.rejection_warehouse)

	def test_rejection_qty_with_no_fg_row_is_noop(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_apply_rejection_entries,
		)

		shift = _create_test_shift(
			shift_date="2026-04-20",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = frappe.new_doc("Stock Entry")
		se.update(
			{
				"purpose": "Manufacture",
				"stock_entry_type": "Manufacture",
				"company": self.company,
				"custom_pea_shift": shift.name,
				"custom_pea_rejection_qty": 5,
			}
		)
		se.append(
			"items",
			{
				"item_code": self.rm_item,
				"qty": 5,
				"s_warehouse": self.rm_warehouse,
			},
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 5, "remark": "No FG row"},
			],
		)
		_apply_rejection_entries(se)

		rejection_rows = [r for r in se.items if r.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 0)

	def test_get_shift_details_for_stock_entry_api(self) -> None:
		from production_entry_app.production_entry_app.api import get_shift_details_for_stock_entry

		self.assertEqual(get_shift_details_for_stock_entry(""), {})

		shift = _create_test_shift(
			shift_date="2026-04-21",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		result = get_shift_details_for_stock_entry(shift.name)
		self.assertEqual(result.get("company"), shift.company)
		self.assertIn("2026-04-21 16:00:00", result.get("custom_pea_planned_start_date") or "")
		self.assertIn("2026-04-22 00:00:00", result.get("custom_pea_planned_end_date") or "")
		self.assertEqual(result.get("from_warehouse"), self.wip_warehouse)

	def test_get_shift_details_for_stock_entry_api_allows_completed_shift(self) -> None:
		from production_entry_app.production_entry_app.api import get_shift_details_for_stock_entry

		shift = _create_test_shift(
			shift_date="2026-04-22",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		shift.end_shift()
		shift.reload()
		self.assertEqual(shift.status, "Completed")

		result = get_shift_details_for_stock_entry(shift.name)

		self.assertEqual(result.get("company"), shift.company)
		self.assertIn("2026-04-22 16:00:00", result.get("custom_pea_planned_start_date") or "")
		self.assertEqual(result.get("from_warehouse"), self.wip_warehouse)

	def test_get_shift_details_for_stock_entry_api_blocks_draft_shift(self) -> None:
		from production_entry_app.production_entry_app.api import get_shift_details_for_stock_entry

		cleanup_running_shifts()
		department = ensure_department("Test Department")
		for existing_name in frappe.get_all(
			"Shift",
			filters={"department": department, "shift_date": "2090-01-23", "shift_label": "2"},
			pluck="name",
		):
			frappe.delete_doc("Shift", existing_name, force=True, ignore_permissions=True)
		draft_shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2090-01-23",
				"planned_start_time": "08:00:00",
			}
		).insert()

		with self.assertRaisesRegex(
			ValidationError, "Only Running or Completed shifts can be linked in Stock Entry"
		):
			get_shift_details_for_stock_entry(draft_shift.name)

	def test_stock_entry_blocks_draft_shift_on_save(self) -> None:
		cleanup_running_shifts()
		department = ensure_department("Test Department")
		for existing_name in frappe.get_all(
			"Shift",
			filters={"department": department, "shift_date": "2090-01-24", "shift_label": "2"},
			pluck="name",
		):
			frappe.delete_doc("Shift", existing_name, force=True, ignore_permissions=True)
		draft_shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2090-01-24",
				"planned_start_time": "08:00:00",
				"work_in_progress_warehouse": self.wip_warehouse,
			}
		).insert()

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_shift = draft_shift.name

		with self.assertRaisesRegex(ValidationError, "Only Running or Completed shifts can be linked"):
			se.save()

	def test_stock_entry_allows_completed_shift_on_save(self) -> None:
		shift = _create_test_shift(
			shift_date="2090-01-25",
			shift_label="2",
			wip_warehouse=self.wip_warehouse,
		)
		shift.end_shift()
		shift.reload()
		self.assertEqual(shift.status, "Completed")

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_shift = shift.name

		se.save()

		self.assertEqual(se.custom_pea_shift, shift.name)
		self.assertEqual(se.branch, shift.branch)

	def test_entry_metrics_with_no_fg_item_sets_die_tool_fields_to_zero(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import _set_entry_metrics

		se = frappe.new_doc("Stock Entry")
		se.purpose = "Manufacture"
		se.stock_entry_type = "Manufacture"
		se.company = self.company

		_set_entry_metrics(se)

		self.assertEqual(float(se.get("custom_pea_die_tool_utilization_pct") or 0), 0.0)
		self.assertEqual(int(se.get("custom_pea_die_tool_maintenance_due") or 0), 0)

	def test_entry_metrics_with_die_tool_disabled_sets_die_tool_fields_to_zero(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import _set_entry_metrics

		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000, has_die_tool=0)

		se = frappe.new_doc("Stock Entry")
		se.purpose = "Manufacture"
		se.stock_entry_type = "Manufacture"
		se.company = self.company
		se.fg_item = self.fg_item

		_set_entry_metrics(se)

		self.assertEqual(float(se.get("custom_pea_die_tool_utilization_pct") or 0), 0.0)
		self.assertEqual(int(se.get("custom_pea_die_tool_maintenance_due") or 0), 0)

	def test_die_tool_warning_metrics_populated_from_counter(self) -> None:
		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000, has_die_tool=1)

		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
		)

		if frappe.db.exists("Die Tool Counter", self.fg_item):
			frappe.db.set_value(
				"Die Tool Counter",
				self.fg_item,
				{
					"current_stroke_count": 900,
					"stroke_capacity": 1000,
					"warning_threshold_pct": 90,
				},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Die Tool Counter",
					"die_tool_item": self.fg_item,
					"current_stroke_count": 900,
					"stroke_capacity": 1000,
					"warning_threshold_pct": 90,
				}
			).insert(ignore_permissions=True)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=50,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertEqual(float(se.get("custom_pea_die_tool_utilization_pct") or 0), 90.0)
		self.assertEqual(int(se.get("custom_pea_die_tool_maintenance_due") or 0), 1)

	def test_shift_reference_planned_dates_for_evening_shift_label_2(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-20",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-20", str(se.custom_pea_planned_start_date))
		self.assertIn("16:00:00", str(se.custom_pea_planned_start_date))
		self.assertIn("2026-04-21", str(se.custom_pea_planned_end_date))
		self.assertIn("00:00:00", str(se.custom_pea_planned_end_date))

	def test_shift_reference_planned_end_rolls_over_when_shift_end_date_missing(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			planned_start_time="20:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		frappe.db.set_value("Shift", shift.name, "shift_end_date", None, update_modified=False)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-16", str(se.custom_pea_planned_end_date))
		self.assertIn("04:00:00", str(se.custom_pea_planned_end_date))

	def test_shift_reference_auto_fills_warehouses(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertEqual(se.from_warehouse, self.wip_warehouse)
		self.assertEqual(se.to_warehouse, self.wip_warehouse)

	def test_shift_reference_preserves_explicit_parent_warehouses(self) -> None:
		explicit_from = _get_or_create_warehouse("SE Hook Explicit From", self.company)
		explicit_to = _get_or_create_warehouse("SE Hook Explicit To", self.company)
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.from_warehouse = explicit_from
		se.to_warehouse = explicit_to
		se.save()

		self.assertEqual(se.from_warehouse, explicit_from)
		self.assertEqual(se.to_warehouse, explicit_to)

	def test_rejection_qty_deducts_from_finished_good(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)
		se.save()

		# Find the true FG row (exclude rejection row flagged as finished item)
		fg_rows = [r for r in se.items if r.is_finished_item and not r.custom_pea_is_rejection_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0].qty, 95)

	def test_rejection_qty_creates_rejection_row(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)
		se.save()

		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].qty, 5)
		self.assertEqual(rejection_rows[0].item_code, self.fg_item)
		self.assertEqual(rejection_rows[0].t_warehouse, self.rejection_warehouse)

	def test_rejection_qty_exceeding_fg_throws_error(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=150,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 150, "remark": "Over rejection"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_row_is_idempotent_on_resave(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()

		# First save: 3 items (RM, FG@90, Rejection@10)
		self.assertEqual(len(se.items), 3)
		fg_rows = [r for r in se.items if r.is_finished_item and not r.custom_pea_is_rejection_item]
		self.assertEqual(fg_rows[0].qty, 90)

		# Re-save should produce the same result
		se.save()
		self.assertEqual(len(se.items), 3)
		fg_rows = [r for r in se.items if r.is_finished_item and not r.custom_pea_is_rejection_item]
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(fg_rows[0].qty, 90)
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].qty, 10)

	def test_rejection_row_target_warehouse_persists_when_user_overrides(self) -> None:
		explicit_rejection_warehouse = _get_or_create_warehouse("SE Hook Explicit Rejection", self.company)
		frappe.db.set_value(
			"Warehouse", explicit_rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		rejection_rows[0].t_warehouse = explicit_rejection_warehouse

		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].t_warehouse, explicit_rejection_warehouse)

	def test_rejection_row_target_warehouse_override_is_respected_on_first_save(self) -> None:
		explicit_rejection_warehouse = _get_or_create_warehouse("SE Hook First Save Rejection", self.company)
		frappe.db.set_value(
			"Warehouse", explicit_rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)

		# Simulate browser state before first save: FG already reduced and rejection row present.
		fg_rows = [r for r in se.items if r.is_finished_item]
		self.assertEqual(len(fg_rows), 1)
		fg_rows[0].qty = 90
		se.append(
			"items",
			{
				"item_code": self.fg_item,
				"qty": 10,
				"uom": fg_rows[0].uom,
				"stock_uom": fg_rows[0].stock_uom,
				"conversion_factor": fg_rows[0].conversion_factor,
				"t_warehouse": explicit_rejection_warehouse,
				"s_warehouse": fg_rows[0].s_warehouse,
				"custom_pea_is_rejection_item": 1,
				"is_finished_item": 1,
				"is_scrap_item": 0,
			},
		)

		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].t_warehouse, explicit_rejection_warehouse)

	def test_rejection_row_target_warehouse_must_be_marked_rejected(self) -> None:
		non_rejected_warehouse = _get_or_create_warehouse("SE Hook Non-Rejection", self.company)
		frappe.db.set_value(
			"Warehouse", non_rejected_warehouse, "is_rejected_warehouse", 0, update_modified=False
		)
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		rejection_rows[0].t_warehouse = non_rejected_warehouse

		with self.assertRaisesRegex(ValidationError, "Rejected Warehouse"):
			se.save()

	def test_rejection_row_latest_idx_warehouse_wins_and_normalizes_rows(self) -> None:
		non_rejected_warehouse = _get_or_create_warehouse("SE Hook Non-Rejection 2", self.company)
		valid_rejected_warehouse = _get_or_create_warehouse("SE Hook Valid Rejection", self.company)
		frappe.db.set_value(
			"Warehouse", non_rejected_warehouse, "is_rejected_warehouse", 0, update_modified=False
		)
		frappe.db.set_value(
			"Warehouse", valid_rejected_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()

		# Legacy/bad state simulation: two rejection rows where last edited row is valid.
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		rejection_rows[0].t_warehouse = non_rejected_warehouse
		se.append(
			"items",
			{
				"item_code": self.fg_item,
				"qty": 10,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"t_warehouse": valid_rejected_warehouse,
				"custom_pea_is_rejection_item": 1,
				"is_finished_item": 1,
				"is_scrap_item": 0,
			},
		)

		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].t_warehouse, valid_rejected_warehouse)

	def test_rejection_row_prefers_valid_rejected_warehouse_among_duplicates(self) -> None:
		non_rejected_warehouse = _get_or_create_warehouse("SE Hook Non-Rejection 3", self.company)
		valid_rejected_warehouse = _get_or_create_warehouse("SE Hook Valid Rejection 2", self.company)
		frappe.db.set_value(
			"Warehouse", non_rejected_warehouse, "is_rejected_warehouse", 0, update_modified=False
		)
		frappe.db.set_value(
			"Warehouse", valid_rejected_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()

		# Duplicate-row simulation where the latest row is invalid but an earlier row is valid.
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		rejection_rows[0].t_warehouse = valid_rejected_warehouse
		se.append(
			"items",
			{
				"item_code": self.fg_item,
				"qty": 10,
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"t_warehouse": non_rejected_warehouse,
				"custom_pea_is_rejection_item": 1,
				"is_finished_item": 1,
				"is_scrap_item": 0,
			},
		)

		se.save()
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].t_warehouse, valid_rejected_warehouse)

	def test_remove_rejection_rows_no_op_when_none_found(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			_remove_existing_rejection_rows,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		original_qty = next(row.qty for row in se.items if row.is_finished_item)
		original_count = len(se.items)

		_remove_existing_rejection_rows(se)

		self.assertEqual(len(se.items), original_count)
		self.assertEqual(next(row.qty for row in se.items if row.is_finished_item), original_qty)

	def test_rejection_qty_zero_produces_no_rejection_row(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-17",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=0,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		rejection_rows = [r for r in se.items if r.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 0)

	def test_unplanned_losses_can_be_added_to_stock_entry(self) -> None:
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)

		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Tea Break",
				"start_time": "10:00:00",
				"end_time": "10:15:00",
			},
		)
		se.save()

		self.assertEqual(len(se.custom_pea_unplanned_losses), 1)
		self.assertEqual(se.custom_pea_unplanned_losses[0].downtime_reason, "Tea Break")
		self.assertEqual(se.custom_pea_unplanned_losses[0].shift, shift.name)

	def test_unplanned_loss_outside_actual_window_throws(self) -> None:
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-18 09:30:00"
		se.custom_pea_actual_end_date = "2026-04-18 10:30:00"
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Setup Time",
				"start_time": "09:00:00",
				"end_time": "09:10:00",
			},
		)

		with self.assertRaisesRegex(ValidationError, "within the Stock Entry actual time window"):
			se.save()

	def test_unplanned_loss_outside_zero_duration_actual_window_throws(self) -> None:
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-18",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-18 09:30:00"
		se.custom_pea_actual_end_date = "2026-04-18 09:30:00"
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Setup Time",
				"start_time": "09:00:00",
				"end_time": "09:10:00",
			},
		)

		with self.assertRaisesRegex(ValidationError, "within the Stock Entry actual time window"):
			se.save()

	def test_unplanned_loss_shift_link_clears_when_shift_is_removed(self) -> None:
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-19",
			wip_warehouse=self.wip_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.append(
			"custom_pea_unplanned_losses",
			{
				"downtime_reason": "Tea Break",
				"start_time": "10:00:00",
				"end_time": "10:15:00",
			},
		)
		se.save()
		self.assertEqual(se.custom_pea_unplanned_losses[0].shift, shift.name)

		se.custom_pea_shift = ""
		se.save()
		self.assertEqual(se.custom_pea_unplanned_losses[0].shift, "")

	def test_draft_stock_entry_rehydrates_updated_planned_end_from_running_shift(self) -> None:
		"""When a Running shift's duration is changed, a new (draft) Stock Entry
		created against that shift must get the updated planned_end_date from the Shift."""
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-20",
			wip_warehouse=self.wip_warehouse,
		)
		# Shift is now Running with 8-hour duration (08:00 -> 16:00)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		# Before changing shift duration, validate to populate planned end
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			validate_stock_entry,
		)

		validate_stock_entry(se)
		original_planned_end = se.custom_pea_planned_end_date

		# Change shift duration to 10 hours (shift end becomes 18:00)
		frappe.db.set_value(
			"Shift",
			shift.name,
			{"shift_duration": "10", "planned_end_time": "18:00:00"},
			update_modified=False,
		)

		# Create a new draft SE and validate - it should pick up the new shift end
		se2 = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		validate_stock_entry(se2)
		updated_planned_end = se2.custom_pea_planned_end_date

		# The updated planned end should be later than the original
		self.assertGreater(updated_planned_end, original_planned_end)

	def test_submitted_stock_entry_is_not_rewritten_by_shift_duration_change(self) -> None:
		"""When a Running shift's duration is changed after a Stock Entry is submitted,
		the submitted Stock Entry must NOT be rewritten/updated by the hook."""
		_ensure_downtime_reasons()
		shift = _create_test_shift(
			shift_date="2026-04-21",
			wip_warehouse=self.wip_warehouse,
		)
		# Shift is Running with 8h (08:00 -> 16:00)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_pea_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_actual_start_date = "2026-04-21 08:00:00"
		se.custom_pea_actual_end_date = "2026-04-21 09:00:00"
		se.save()
		frappe.db.set_value("Stock Entry", se.name, "docstatus", 1, update_modified=False)
		submitted_planned_start = se.custom_pea_planned_start_date
		submitted_planned_end = se.custom_pea_planned_end_date

		# Change shift duration to 10 hours (now ends at 18:00)
		frappe.db.set_value(
			"Shift",
			shift.name,
			{"shift_duration": "10", "planned_end_time": "18:00:00"},
			update_modified=False,
		)

		# Re-validate the submitted doc - hook should NOT rewrite it
		se_reloaded = frappe.get_doc("Stock Entry", se.name)
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			validate_stock_entry,
		)

		validate_stock_entry(se_reloaded)

		# The submitted doc's planned dates must remain unchanged
		self.assertEqual(se_reloaded.custom_pea_planned_start_date, submitted_planned_start)
		self.assertEqual(se_reloaded.custom_pea_planned_end_date, submitted_planned_end)


class TestOverlapValidation(FrappeTestCase):
	# Shift dates used by tests in this class (May 1-12, 2026)
	_SHIFT_DATES: ClassVar[list[str]] = [f"2026-05-{d:02d}" for d in range(1, 13)]

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		context = bootstrap_manufacturing_test_context("SE Overlap")
		cls.company = context["company"]
		cls.wip_warehouse = context["wip_warehouse"]
		cls.rm_warehouse = context["rm_warehouse"]
		cls.fg_warehouse = context["fg_warehouse"]
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")
		cls.workstation_1 = "SE Hook WS-1"
		cls.workstation_2 = "SE Hook WS-2"
		cls.operator_1 = "SE Hook Operator-1"
		cls.operator_2 = "SE Hook Operator-2"
		cls.employee_name = _get_or_create_employee("SE-HOOK-EMP-OVERLAP")
		ensure_workstation(cls.workstation_1, standard_spm=2)
		ensure_workstation(cls.workstation_2, standard_spm=2)
		ensure_operator(cls.operator_1)
		ensure_operator(cls.operator_2)

	def setUp(self) -> None:
		cleanup_running_shifts()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure running shift cleanup is visible
		self.company = self.__class__.company
		self.wip_warehouse = self.__class__.wip_warehouse
		self.rm_warehouse = self.__class__.rm_warehouse
		self.fg_warehouse = self.__class__.fg_warehouse
		self.fg_item = self.__class__.fg_item
		self.rm_item = self.__class__.rm_item
		self.employee_name = self.__class__.employee_name

	def tearDown(self) -> None:
		frappe.db.rollback()

	@classmethod
	def tearDownClass(cls) -> None:
		department = ensure_department("Test Department")
		for shift_date in cls._SHIFT_DATES:
			for label in ("1", "2"):
				for name in frappe.get_all(
					"Shift",
					filters={"department": department, "shift_date": shift_date, "shift_label": label},
					pluck="name",
				):
					frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed to persist cleanup
		super().tearDownClass()

	def _create_entry(
		self,
		*,
		shift_name: str | None,
		start: str | None = None,
		end: str | None = None,
		workstation: str | None = None,
		operator: str | None = None,
		purpose: str = "Manufacture",
	) -> frappe.Document:
		if purpose == "Manufacture":
			se = _create_manufacture_stock_entry(
				company=self.company,
				fg_item=self.fg_item,
				rm_item=self.rm_item,
				custom_pea_shift=shift_name,
				fg_warehouse=self.fg_warehouse,
				rm_warehouse=self.rm_warehouse,
			)
		else:
			se = frappe.get_doc(
				{
					"doctype": "Stock Entry",
					"purpose": "Material Transfer",
					"stock_entry_type": "Material Transfer",
					"company": self.company,
					"items": [
						{
							"item_code": self.rm_item,
							"qty": 1,
							"s_warehouse": self.rm_warehouse,
							"t_warehouse": self.fg_warehouse,
							"basic_rate": 50,
						}
					],
				}
			)
			if shift_name:
				se.custom_pea_shift = shift_name

		if start:
			se.custom_pea_actual_start_date = start
		if end:
			se.custom_pea_actual_end_date = end
		if workstation:
			se.custom_pea_workstation = workstation
		if operator:
			se.custom_pea_operator = operator
		return se

	def test_workstation_overlap_blocks_overlapping_entry(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-01", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-01 08:00:00",
			end="2026-05-01 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-01 08:30:00",
			end="2026-05-01 09:30:00",
			workstation=self.workstation_1,
		)
		with self.assertRaisesRegex(ValidationError, "Workstation"):
			second.save()

	def test_workstation_overlap_allows_different_workstations(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-02", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-02 08:00:00",
			end="2026-05-02 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-02 08:30:00",
			end="2026-05-02 09:30:00",
			workstation=self.workstation_2,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_workstation_overlap_allows_adjacent_times(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-03", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-03 08:00:00",
			end="2026-05-03 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-03 09:00:00",
			end="2026-05-03 10:00:00",
			workstation=self.workstation_1,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_workstation_overlap_excludes_cancelled_entries(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-04", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-04 08:00:00",
			end="2026-05-04 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()
		frappe.db.set_value("Stock Entry", first.name, "docstatus", 2, update_modified=False)

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-04 08:30:00",
			end="2026-05-04 09:30:00",
			workstation=self.workstation_1,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_workstation_overlap_allows_resave(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-05", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 08:00:00",
			end="2026-05-05 09:00:00",
			workstation=self.workstation_1,
		)
		se.save()
		se.save()
		self.assertTrue(bool(se.name))

	def test_workstation_overlap_skips_query_when_overlap_inputs_are_unchanged(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-05", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 10:00:00",
			end="2026-05-05 11:00:00",
			workstation=self.workstation_1,
		)
		se.save()
		se.posting_time = "10:30:00"

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_stock_entry",
			return_value=None,
		) as find_overlap:
			se.save()

		find_overlap.assert_not_called()

	def test_workstation_overlap_runs_query_when_actual_window_changes(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-05", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 12:00:00",
			end="2026-05-05 13:00:00",
			workstation=self.workstation_1,
		)
		se.save()
		se.custom_pea_actual_end_date = "2026-05-05 13:15:00"

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_stock_entry",
			return_value=None,
		) as find_overlap:
			se.save()

		find_overlap.assert_called_once_with(se, "custom_pea_workstation", self.workstation_1)

	def test_workstation_overlap_skipped_without_actual_times(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-06", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-06 08:00:00",
			end="2026-05-06 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			workstation=self.workstation_1,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_workstation_overlap_skipped_without_workstation(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-07", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-07 08:00:00",
			end="2026-05-07 09:00:00",
			workstation=self.workstation_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-07 08:30:00",
			end="2026-05-07 09:30:00",
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_workstation_error_is_prioritized_when_both_workstation_and_operator_overlap(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-08",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-08 16:00:00",
			end="2026-05-08 17:00:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-08 16:30:00",
			end="2026-05-08 17:30:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
		)
		with self.assertRaisesRegex(ValidationError, "Workstation"):
			second.save()

	def test_operator_overlap_blocks_overlapping_entry(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-08", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-08 08:00:00",
			end="2026-05-08 09:00:00",
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-08 08:30:00",
			end="2026-05-08 09:30:00",
			operator=self.operator_1,
		)
		with self.assertRaisesRegex(ValidationError, "Operator"):
			second.save()

	def test_operator_overlap_allows_different_operators(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-09", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-09 08:00:00",
			end="2026-05-09 09:00:00",
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-09 08:30:00",
			end="2026-05-09 09:30:00",
			operator=self.operator_2,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_operator_overlap_allows_adjacent_times(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-10", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-10 08:00:00",
			end="2026-05-10 09:00:00",
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-10 09:00:00",
			end="2026-05-10 10:00:00",
			operator=self.operator_1,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_operator_overlap_excludes_cancelled_entries(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-11", wip_warehouse=self.wip_warehouse)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-11 08:00:00",
			end="2026-05-11 09:00:00",
			operator=self.operator_1,
		)
		first.save()
		frappe.db.set_value("Stock Entry", first.name, "docstatus", 2, update_modified=False)

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-11 08:30:00",
			end="2026-05-11 09:30:00",
			operator=self.operator_1,
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_operator_overlap_allows_resave(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-12", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-12 08:00:00",
			end="2026-05-12 09:00:00",
			operator=self.operator_1,
		)
		se.save()
		se.save()
		self.assertTrue(bool(se.name))

	def test_operator_overlap_skips_query_when_overlap_inputs_are_unchanged(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-12", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-12 10:00:00",
			end="2026-05-12 11:00:00",
			operator=self.operator_1,
		)
		se.save()
		se.posting_time = "10:30:00"

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_stock_entry",
			return_value=None,
		) as find_overlap:
			se.save()

		find_overlap.assert_not_called()

	def test_operator_overlap_runs_query_when_operator_changes(self) -> None:
		shift = _create_test_shift(shift_date="2026-05-12", wip_warehouse=self.wip_warehouse)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-12 12:00:00",
			end="2026-05-12 13:00:00",
			operator=self.operator_1,
		)
		se.save()
		se.custom_pea_operator = self.operator_2

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_stock_entry",
			return_value=None,
		) as find_overlap:
			se.save()

		find_overlap.assert_called_once_with(se, "custom_pea_operator", self.operator_2)

	def test_operator_overlap_skipped_without_operator(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-01",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-01 16:00:00",
			end="2026-05-01 17:00:00",
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-01 16:30:00",
			end="2026-05-01 17:30:00",
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_downtime_overlap_blocks_workstation_with_downtime(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-02",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		_create_downtime_entry(
			workstation=self.workstation_1,
			operator=self.employee_name,
			from_time="2026-05-02 16:00:00",
			to_time="2026-05-02 17:00:00",
		)

		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-02 16:30:00",
			end="2026-05-02 17:30:00",
			workstation=self.workstation_1,
		)
		with self.assertRaisesRegex(ValidationError, "downtime"):
			se.save()

	def test_downtime_overlap_allows_different_workstation(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-03",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		_create_downtime_entry(
			workstation=self.workstation_2,
			operator=self.employee_name,
			from_time="2026-05-03 16:00:00",
			to_time="2026-05-03 17:00:00",
		)

		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-03 16:30:00",
			end="2026-05-03 17:30:00",
			workstation=self.workstation_1,
		)
		se.save()
		self.assertTrue(bool(se.name))

	def test_downtime_overlap_allows_non_overlapping_times(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-04",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		_create_downtime_entry(
			workstation=self.workstation_1,
			operator=self.employee_name,
			from_time="2026-05-04 16:00:00",
			to_time="2026-05-04 17:00:00",
		)

		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-04 17:00:00",
			end="2026-05-04 18:00:00",
			workstation=self.workstation_1,
		)
		se.save()
		self.assertTrue(bool(se.name))

	def test_downtime_overlap_partial_overlap_blocks(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-05",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		_create_downtime_entry(
			workstation=self.workstation_1,
			operator=self.employee_name,
			from_time="2026-05-05 16:00:00",
			to_time="2026-05-05 18:00:00",
		)

		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 17:30:00",
			end="2026-05-05 18:30:00",
			workstation=self.workstation_1,
		)
		with self.assertRaisesRegex(ValidationError, "downtime"):
			se.save()

	def test_downtime_overlap_skips_query_when_overlap_inputs_are_unchanged(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-05",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 18:30:00",
			end="2026-05-05 19:30:00",
			workstation=self.workstation_1,
		)
		se.save()
		se.posting_time = "18:45:00"

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_downtime_entry",
			return_value=None,
		) as find_downtime:
			se.save()

		find_downtime.assert_not_called()

	def test_downtime_overlap_runs_query_when_workstation_changes(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-05",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		se = self._create_entry(
			shift_name=shift.name,
			start="2026-05-05 20:00:00",
			end="2026-05-05 21:00:00",
			workstation=self.workstation_1,
		)
		se.save()
		se.custom_pea_workstation = self.workstation_2

		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks._find_overlapping_downtime_entry",
			return_value=None,
		) as find_downtime:
			se.save()

		find_downtime.assert_called_once()
		args = find_downtime.call_args.args
		self.assertEqual(args[0], self.workstation_2)
		self.assertEqual(str(args[1]), "2026-05-05 20:00:00")
		self.assertEqual(str(args[2]), "2026-05-05 21:00:00")

	def test_no_overlap_validation_for_non_manufacture(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-06",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-06 16:00:00",
			end="2026-05-06 17:00:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=shift.name,
			start="2026-05-06 16:30:00",
			end="2026-05-06 17:30:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
			purpose="Material Transfer",
		)
		second.save()
		self.assertTrue(bool(second.name))

	def test_no_overlap_validation_without_shift(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-05-07",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		first = self._create_entry(
			shift_name=shift.name,
			start="2026-05-07 16:00:00",
			end="2026-05-07 17:00:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
		)
		first.save()

		second = self._create_entry(
			shift_name=None,
			start="2026-05-07 16:30:00",
			end="2026-05-07 17:30:00",
			workstation=self.workstation_1,
			operator=self.operator_1,
		)
		second.save()
		self.assertTrue(bool(second.name))


class TestGetItemsWithRejection(FrappeTestCase):
	"""Tests for the get_items_with_rejection API."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_stock_entry_metric_fields()
		context = bootstrap_manufacturing_test_context("SE Rejection")
		cls.company = context["company"]
		cls.wip_warehouse = context["wip_warehouse"]
		cls.rm_warehouse = context["rm_warehouse"]
		cls.rejection_warehouse = context["rejection_warehouse"]
		cls.fg_warehouse = context["fg_warehouse"]
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")
		cls.bom_no = _get_or_create_bom(cls.fg_item, cls.rm_item, cls.company)

	def setUp(self) -> None:
		cleanup_running_shifts()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure running shift cleanup is visible
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		_ensure_stock_entry_metric_fields()
		context = bootstrap_manufacturing_test_context("SE Rejection")
		self.company = context["company"]
		self.wip_warehouse = context["wip_warehouse"]
		self.rm_warehouse = context["rm_warehouse"]
		self.rejection_warehouse = context["rejection_warehouse"]
		self.fg_warehouse = context["fg_warehouse"]
		self.fg_item = _get_or_create_item("_Test FG Item For Shift")
		self.rm_item = _get_or_create_item("_Test RM Item For Shift")
		self.bom_no = _get_or_create_bom(self.fg_item, self.rm_item, self.company)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def _call_api(self, **overrides) -> list[dict]:
		"""Build a Stock Entry doc dict, serialize it, and call get_items_with_rejection."""
		from production_entry_app.production_entry_app.api import get_items_with_rejection

		doc_dict = {
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": self.company,
			"from_bom": 1,
			"bom_no": self.bom_no,
			"fg_completed_qty": 100,
			"custom_pea_rejection_qty": 0,
			"from_warehouse": self.rm_warehouse,
			"to_warehouse": self.fg_warehouse,
		}
		doc_dict.update(overrides)
		return get_items_with_rejection(json.dumps(doc_dict))

	def _make_alternative_bom_context(self, suffix: str, allow_alternative_item: int = 1) -> dict:
		fg_item = _get_or_create_item(f"_Test FG Alt Direct {suffix}")
		rm_item = _get_or_create_item(f"_Test RM Alt Direct {suffix}")
		alt_item = _get_or_create_item(f"_Test RM Alt Direct Substitute {suffix}")
		frappe.db.set_value("Item", rm_item, "allow_alternative_item", 1)
		frappe.db.set_value("Item", alt_item, "allow_alternative_item", 1)
		if not frappe.db.exists(
			"Item Alternative",
			{"item_code": rm_item, "alternative_item_code": alt_item},
		):
			frappe.get_doc(
				{
					"doctype": "Item Alternative",
					"item_code": rm_item,
					"alternative_item_code": alt_item,
					"two_way": 1,
				}
			).insert(ignore_permissions=True)
		bom_no = _get_or_create_bom(
			fg_item,
			rm_item,
			self.company,
			rm_qty=1,
			allow_alternative_item=allow_alternative_item,
		)
		return {"fg_item": fg_item, "rm_item": rm_item, "alt_item": alt_item, "bom_no": bom_no}

	def _make_direct_manufacture_entry_with_alternative(self, context: dict) -> frappe.Document:
		se = _create_bom_stock_entry(
			company=self.company,
			bom_no=context["bom_no"],
			fg_completed_qty=100,
			from_warehouse=self.rm_warehouse,
			to_warehouse=self.fg_warehouse,
		)
		replaced = False
		for row in se.items:
			if row.item_code == context["rm_item"]:
				row.item_code = context["alt_item"]
				row.original_item = context["rm_item"]
				row.allow_alternative_item = 1
				replaced = True
				break
		self.assertTrue(replaced, "Expected BOM RM row to be replaced with alternative item")
		return se

	def test_get_items_with_rejection_returns_bom_items(self) -> None:
		"""API should return at least RM + FG rows from BOM."""
		items = self._call_api()
		item_codes = [r["item_code"] for r in items]
		self.assertIn(self.rm_item, item_codes)
		self.assertIn(self.fg_item, item_codes)

	def test_get_items_with_rejection_marks_bom_rm_as_alternative_allowed(self) -> None:
		context = self._make_alternative_bom_context("Allowed", allow_alternative_item=1)

		items = self._call_api(bom_no=context["bom_no"])

		rm_rows = [row for row in items if row.get("item_code") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertEqual(int(rm_rows[0].get("allow_alternative_item") or 0), 1)

	def test_get_items_with_rejection_does_not_mark_bom_rm_when_alternative_not_allowed(self) -> None:
		context = self._make_alternative_bom_context("NotAllowed", allow_alternative_item=0)

		items = self._call_api(bom_no=context["bom_no"])

		rm_rows = [row for row in items if row.get("item_code") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertEqual(int(rm_rows[0].get("allow_alternative_item") or 0), 0)

	def test_direct_manufacture_valid_alternative_item_validates(self) -> None:
		context = self._make_alternative_bom_context("Valid", allow_alternative_item=1)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		se.run_method("validate")

		rm_rows = [row for row in se.items if row.get("original_item") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertEqual(rm_rows[0].item_code, context["alt_item"])

	def test_direct_manufacture_alternative_requires_bom_row_permission(self) -> None:
		context = self._make_alternative_bom_context("BomDenied", allow_alternative_item=0)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		with self.assertRaisesRegex(ValidationError, "does not allow alternative items"):
			se.run_method("validate")

	def test_direct_manufacture_alternative_requires_item_alternative_record(self) -> None:
		context = self._make_alternative_bom_context("MissingAlternative", allow_alternative_item=1)
		frappe.delete_doc(
			"Item Alternative",
			frappe.db.get_value(
				"Item Alternative",
				{"item_code": context["rm_item"], "alternative_item_code": context["alt_item"]},
				"name",
			),
			ignore_permissions=True,
		)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		with self.assertRaisesRegex(ValidationError, "is not configured as an alternative"):
			se.run_method("validate")

	def test_direct_manufacture_alternative_requires_original_item_for_non_bom_item(self) -> None:
		context = self._make_alternative_bom_context("MissingOriginal", allow_alternative_item=1)
		se = self._make_direct_manufacture_entry_with_alternative(context)
		for row in se.items:
			if row.get("item_code") == context["alt_item"]:
				row.original_item = ""
				break

		with self.assertRaisesRegex(ValidationError, "is not part of BOM"):
			se.run_method("validate")

	def test_direct_manufacture_same_original_item_still_requires_bom_membership(self) -> None:
		context = self._make_alternative_bom_context("SameOriginal", allow_alternative_item=1)
		se = self._make_direct_manufacture_entry_with_alternative(context)
		for row in se.items:
			if row.get("item_code") == context["alt_item"]:
				row.original_item = context["alt_item"]
				break

		with self.assertRaisesRegex(ValidationError, "is not part of BOM"):
			se.run_method("validate")

	def test_alternative_allowed_lookup_includes_child_bom_items(self) -> None:
		suffix = frappe.generate_hash(length=8)
		parent_fg = _get_or_create_item(f"_Test Parent FG Alt {suffix}")
		child_fg = _get_or_create_item(f"_Test Child FG Alt {suffix}")
		child_rm = _get_or_create_item(f"_Test Child RM Alt {suffix}")

		child_bom = _get_or_create_bom(
			child_fg,
			child_rm,
			self.company,
			allow_alternative_item=1,
		)
		parent_bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": parent_fg,
				"company": self.company,
				"quantity": 1,
				"is_active": 1,
				"is_default": 1,
				"items": [
					{
						"item_code": child_fg,
						"qty": 1,
						"rate": 50,
						"bom_no": child_bom,
						"allow_alternative_item": 0,
					}
				],
			}
		)
		parent_bom.insert(ignore_permissions=True)
		parent_bom.submit()

		self.assertIn(child_rm, get_bom_alternative_allowed_items(parent_bom.name))

	def test_get_or_create_bom_does_not_reuse_bom_with_different_alternative_flag(self) -> None:
		suffix = frappe.generate_hash(length=8)
		fg_item = _get_or_create_item(f"_Test FG Alt Reuse {suffix}")
		rm_item = _get_or_create_item(f"_Test RM Alt Reuse {suffix}")

		first_bom = _get_or_create_bom(
			fg_item,
			rm_item,
			self.company,
			allow_alternative_item=0,
		)
		second_bom = _get_or_create_bom(
			fg_item,
			rm_item,
			self.company,
			allow_alternative_item=1,
		)

		self.assertNotEqual(second_bom, first_bom)

	def test_get_items_with_rejection_deducts_from_fg(self) -> None:
		"""FG row qty should be reduced by rejection qty."""
		shift = _create_test_shift(
			shift_date="2026-04-20",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		items = self._call_api(
			custom_pea_rejection_qty=10,
			custom_pea_shift=shift.name,
		)
		fg_rows = [
			r for r in items if r.get("is_finished_item") and not r.get("custom_pea_is_rejection_item")
		]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0]["qty"], 90)

	def test_get_items_with_rejection_adds_rejection_row(self) -> None:
		"""Rejection row must have expected flags, qty, rejection warehouse, and same basic_rate as FG."""
		shift = _create_test_shift(
			shift_date="2026-04-21",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		items = self._call_api(
			custom_pea_rejection_qty=10,
			custom_pea_shift=shift.name,
		)
		fg_rows = [
			r for r in items if r.get("is_finished_item") and not r.get("custom_pea_is_rejection_item")
		]
		rejection_rows = [r for r in items if r.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 1)
		rr = rejection_rows[0]
		self.assertEqual(rr["qty"], 10)
		self.assertEqual(rr["item_code"], self.fg_item)
		self.assertEqual(rr["t_warehouse"], self.rejection_warehouse)
		self.assertFalse(rr.get("is_scrap_item"), "rejection row must have is_scrap_item=0")
		self.assertTrue(rr.get("is_finished_item"), "rejection row must have is_finished_item=1")
		# basic_rate must match FG row
		fg_rate = fg_rows[0].get("basic_rate", 0)
		self.assertGreater(fg_rate, 0, "FG row must have a basic_rate")
		self.assertEqual(rr.get("basic_rate"), fg_rate, "rejection basic_rate must equal FG basic_rate")

	def test_get_items_with_rejection_does_not_mark_rejection_row_as_alternative_allowed(self) -> None:
		context = self._make_alternative_bom_context("RejectionRow", allow_alternative_item=1)
		shift = _create_test_shift(
			shift_date="2026-04-24",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		items = self._call_api(
			bom_no=context["bom_no"],
			custom_pea_rejection_qty=10,
			custom_pea_shift=shift.name,
		)

		rejection_rows = [row for row in items if row.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(int(rejection_rows[0].get("allow_alternative_item") or 0), 0)

	def test_get_items_with_rejection_returns_native_alternative_dialog_fields(self) -> None:
		context = self._make_alternative_bom_context("DialogFields", allow_alternative_item=1)

		items = self._call_api(bom_no=context["bom_no"])

		rm_row = next(row for row in items if row.get("item_code") == context["rm_item"])
		self.assertEqual(int(rm_row.get("allow_alternative_item") or 0), 1)
		self.assertEqual(rm_row.get("s_warehouse"), self.rm_warehouse)
		self.assertIsNotNone(rm_row.get("actual_qty"))
		self.assertIsInstance(float(rm_row.get("actual_qty")), float)
		self.assertIn("original_item", rm_row)

	def test_rejection_row_basic_rate_matches_fg_on_save(self) -> None:
		"""Rejection row basic_rate must match FG row basic_rate when saved via validate hook."""
		shift = _create_test_shift(
			shift_date="2026-04-23",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_pea_shift=shift.name,
			custom_pea_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)
		# Set a known basic_rate on the FG row before save
		for row in se.items:
			if row.is_finished_item:
				row.basic_rate = 200
		se.save()

		fg_rows = [r for r in se.items if r.is_finished_item and not r.custom_pea_is_rejection_item]
		rejection_rows = [r for r in se.items if r.custom_pea_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].basic_rate, fg_rows[0].basic_rate)

	def test_custom_is_rejection_item_field_is_visible(self) -> None:
		"""The custom_pea_is_rejection_item Custom Field must not be hidden."""
		hidden = frappe.db.get_value(
			"Custom Field", "Stock Entry Detail-custom_pea_is_rejection_item", "hidden"
		)
		self.assertFalse(hidden, "custom_pea_is_rejection_item must be visible (hidden=0)")

	def test_get_items_with_rejection_zero_rejection(self) -> None:
		"""No rejection row when rejection_qty is 0."""
		items = self._call_api(custom_pea_rejection_qty=0)
		rejection_rows = [r for r in items if r.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 0)

	def test_get_items_with_rejection_mirrors_browser_flow(self) -> None:
		"""Simulate browser: doc already has items from prior get_items() call."""
		shift = _create_test_shift(
			shift_date="2026-04-22",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		# First, build a SE with BOM items (like ERPNext auto-populate on fg_completed_qty change)
		se = _create_bom_stock_entry(
			company=self.company,
			bom_no=self.bom_no,
			fg_completed_qty=100,
			from_warehouse=self.rm_warehouse,
			to_warehouse=self.fg_warehouse,
		)
		# Now build the dict the browser would send (includes existing items)
		doc_dict = se.as_dict()
		doc_dict["custom_pea_rejection_qty"] = 15
		doc_dict["custom_pea_shift"] = shift.name

		from production_entry_app.production_entry_app.api import get_items_with_rejection

		items = get_items_with_rejection(json.dumps(doc_dict, default=str))

		fg_rows = [
			r for r in items if r.get("is_finished_item") and not r.get("custom_pea_is_rejection_item")
		]
		rejection_rows = [r for r in items if r.get("custom_pea_is_rejection_item")]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0]["qty"], 85)
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0]["qty"], 15)
		self.assertFalse(rejection_rows[0].get("is_scrap_item"))
		self.assertTrue(rejection_rows[0].get("is_finished_item"))
		self.assertEqual(rejection_rows[0]["t_warehouse"], self.rejection_warehouse)

	def test_rejection_qty_field_depends_on_from_bom(self) -> None:
		"""The custom_pea_rejection_qty Custom Field should have depends_on set."""
		depends_on = frappe.db.get_value("Custom Field", "Stock Entry-custom_pea_rejection_qty", "depends_on")
		self.assertEqual(
			depends_on,
			'eval:doc.custom_pea_stock_entry_purpose=="Manufacture" && (doc.from_bom)',
		)

	def test_actual_datetime_helper_fields_exist(self) -> None:
		meta = frappe.get_meta("Stock Entry")
		for fieldname, fieldtype in (
			("custom_pea_actual_start_date_input", "Date"),
			("custom_pea_actual_start_time_input", "Data"),
			("custom_pea_actual_end_date_input", "Date"),
			("custom_pea_actual_end_time_input", "Data"),
		):
			field = meta.get_field(fieldname)
			self.assertTrue(field, f"Expected Stock Entry field {fieldname} to exist")
			self.assertEqual(field.fieldtype, fieldtype)
			self.assertEqual(int(field.no_copy or 0), 1)
			self.assertEqual(int(field.print_hide or 0), 1)
			self.assertEqual(int(field.search_index or 0), 0)

	def test_actual_datetime_helper_fields_stay_in_operation_details_column(self) -> None:
		meta = frappe.get_meta("Stock Entry")
		self.assertEqual(
			meta.get_field("custom_pea_operation_details_col_break").insert_after,
			"custom_pea_actual_end_date",
		)
		self.assertEqual(
			meta.get_field("custom_pea_actual_start_date_input").insert_after,
			"custom_pea_operation_details_col_break",
		)
		self.assertEqual(
			meta.get_field("custom_pea_actual_start_time_input").insert_after,
			"custom_pea_actual_start_date_input",
		)
		self.assertEqual(
			meta.get_field("custom_pea_actual_end_date_input").insert_after,
			"custom_pea_actual_start_time_input",
		)
		self.assertEqual(
			meta.get_field("custom_pea_actual_end_time_input").insert_after,
			"custom_pea_actual_end_date_input",
		)

	def test_canonical_actual_datetime_fields_are_visible_below_planned_end_date(self) -> None:
		meta = frappe.get_meta("Stock Entry")
		start_field = meta.get_field("custom_pea_actual_start_date")
		end_field = meta.get_field("custom_pea_actual_end_date")
		self.assertTrue(start_field)
		self.assertTrue(end_field)
		self.assertEqual(int(start_field.hidden or 0), 0)
		self.assertEqual(int(end_field.hidden or 0), 0)
		self.assertEqual(int(start_field.read_only or 0), 1)
		self.assertEqual(int(end_field.read_only or 0), 1)
		self.assertEqual(start_field.insert_after, "custom_pea_planned_end_date")
		self.assertEqual(end_field.insert_after, "custom_pea_actual_start_date")

	def test_metrics_note_field_exists_below_operator_efficiency(self) -> None:
		meta = frappe.get_meta("Stock Entry")
		field = meta.get_field("custom_pea_metrics_note")
		self.assertTrue(field)
		self.assertEqual(field.fieldtype, "Small Text")
		self.assertEqual(int(field.read_only or 0), 1)
		self.assertEqual(field.insert_after, "custom_pea_operator_efficiency_pct")

	@classmethod
	def tearDownClass(cls) -> None:
		# Clean up any Running shifts used in this class
		department = ensure_department("Test Department")
		for day in ("20", "21", "22", "23"):
			for name in frappe.get_all(
				"Shift",
				filters={"department": department, "shift_date": f"2026-04-{day}", "shift_label": "1"},
				pluck="name",
			):
				frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed to persist cleanup
		super().tearDownClass()


class TestDieToolCounter(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_die_tool_maintenance_log_doctype()
		_ensure_die_tool_counter_doctype()
		_ensure_item_die_tool_fields()
		cls.company = resolve_test_company()
		abbr = get_company_abbr(cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"DT RM Test - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"DT FG Test - {abbr}", cls.company)
		suffix = frappe.generate_hash(length=6)
		cls.rm_item = _get_or_create_item(f"_Test Die Tool RM {suffix}")
		cls.fg_item = _get_or_create_item(f"_Test Die Tool FG {suffix}")
		_set_item_die_tool_fields(cls.fg_item, strokes_per_unit=12, stroke_capacity=1000)
		strokes = frappe.db.get_value("Item", cls.fg_item, "custom_pea_strokes_per_unit")
		if not strokes:
			frappe.db.set_value("Item", cls.fg_item, "custom_pea_strokes_per_unit", 12)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit - persist stroke config
		frappe.db.delete("Die Tool Maintenance Log", {"die_tool_item": cls.fg_item})
		frappe.db.delete("Die Tool Counter", {"die_tool_item": cls.fg_item})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - clear prior data

	def setUp(self) -> None:
		_ensure_die_tool_maintenance_log_doctype()
		_ensure_die_tool_counter_doctype()
		_ensure_item_die_tool_fields()
		self.company = resolve_test_company()
		abbr = get_company_abbr(self.company)
		self.rm_warehouse = _get_or_create_warehouse(f"DT RM Test - {abbr}", self.company)
		self.fg_warehouse = _get_or_create_warehouse(f"DT FG Test - {abbr}", self.company)
		self.rm_item = _get_or_create_item(self.rm_item)
		self.fg_item = _get_or_create_item(self.fg_item)
		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000)
		frappe.db.delete("Die Tool Maintenance Log", {"die_tool_item": self.fg_item})
		frappe.db.delete("Die Tool Counter", {"die_tool_item": self.fg_item})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - isolate tests

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_die_tool_counter_created_on_submit(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_submit_stock_entry,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=10,
			rm_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_rejection_qty = 2

		on_submit_stock_entry(se, "on_submit")

		counter = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(counter.current_stroke_count, (10 + 2) * 12)
		self.assertEqual(counter.stroke_capacity, 1000)

	def test_atomic_increment_does_not_lose_updates(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_submit_stock_entry,
		)

		first = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=1,
			rm_qty=1,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		second = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=2,
			rm_qty=2,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)

		on_submit_stock_entry(first, "on_submit")
		on_submit_stock_entry(second, "on_submit")

		self.assertEqual(
			float(frappe.db.get_value("Die Tool Counter", self.fg_item, "current_stroke_count") or 0),
			36.0,
		)

	def test_die_tool_counter_decrements_on_cancel(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_cancel_stock_entry,
			on_submit_stock_entry,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=5,
			rm_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_pea_rejection_qty = 1

		on_submit_stock_entry(se, "on_submit")
		on_cancel_stock_entry(se, "on_cancel")

		counter = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(counter.current_stroke_count, 0)

	def test_cache_invalidated_on_stock_entry_submit(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_submit_stock_entry,
		)

		shift_name = "SHIFT-CACHE-TEST-2026-04-20.1"
		doc = frappe._dict({"custom_pea_shift": shift_name})
		with (
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.access_control.can_use_production_entry_app",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.update_counter_for_stock_entry"
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.cache"
			) as cache_fn,
		):
			on_submit_stock_entry(doc, "on_submit")

		cache_fn.return_value.delete_value.assert_called_once_with(f"pea:shift_summary:{shift_name}")

	def test_cache_invalidated_on_stock_entry_cancel(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_cancel_stock_entry,
		)

		shift_name = "SHIFT-CACHE-TEST-2026-04-20.1"
		doc = frappe._dict({"custom_pea_shift": shift_name})
		with (
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.access_control.can_use_production_entry_app",
				return_value=True,
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.update_counter_for_stock_entry"
			),
			patch(
				"production_entry_app.production_entry_app.overrides.stock_entry_hooks.frappe.cache"
			) as cache_fn,
		):
			on_cancel_stock_entry(doc, "on_cancel")

		cache_fn.return_value.delete_value.assert_called_once_with(f"pea:shift_summary:{shift_name}")

	def test_die_tool_counter_resets_on_maintenance_log_submit(self) -> None:
		if frappe.db.exists("Die Tool Counter", self.fg_item):
			frappe.db.set_value(
				"Die Tool Counter",
				self.fg_item,
				{
					"current_stroke_count": 120,
					"stroke_capacity": 1000,
				},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Die Tool Counter",
					"die_tool_item": self.fg_item,
					"current_stroke_count": 120,
					"stroke_capacity": 1000,
				}
			).insert(ignore_permissions=True)

		log = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.fg_item,
				"maintenance_date": "2026-04-30 08:00:00",
				"remarks": "Reset counter",
			}
		)
		log.on_submit()

		counter = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(counter.current_stroke_count, 0)

	def test_die_tool_maintenance_autoname_uses_maintenance_date(self) -> None:
		from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
			DieToolMaintenanceLog,
		)

		log = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.fg_item,
				"maintenance_date": "2026-05-01 10:00:00",
			}
		)
		DieToolMaintenanceLog.autoname(log)

		item_code = self.fg_item.replace(" ", "-")
		self.assertIn(f"DTML-{item_code}-2026-05-01.", log.name)

	def test_die_tool_maintenance_autoname_defaults_to_today(self) -> None:
		from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
			DieToolMaintenanceLog,
		)

		log = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.fg_item,
			}
		)
		DieToolMaintenanceLog.autoname(log)

		item_code = self.fg_item.replace(" ", "-")
		today = frappe.utils.nowdate()
		self.assertIn(f"DTML-{item_code}-{today}.", log.name)

	def test_die_tool_maintenance_autoname_sanitizes_item_code(self) -> None:
		from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
			DieToolMaintenanceLog,
		)

		item_code = "DIE-01_A [B]&$"
		expected = "DIE-01_A--B---"

		log = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": item_code,
				"maintenance_date": "2026-05-02 10:00:00",
			}
		)
		DieToolMaintenanceLog.autoname(log)

		self.assertIn(f"DTML-{expected}-2026-05-02.", log.name)

	def test_get_die_tool_counter_includes_warning_signal(self) -> None:
		from production_entry_app.production_entry_app.api import get_die_tool_counter

		counter = frappe.get_doc(
			{
				"doctype": "Die Tool Counter",
				"die_tool_item": self.fg_item,
				"current_stroke_count": 900,
				"stroke_capacity": 1000,
				"warning_threshold_pct": 90,
			}
		).insert(ignore_permissions=True)

		result = get_die_tool_counter(counter.die_tool_item)
		self.assertEqual(float(result.get("utilization_pct") or 0), 90.0)
		self.assertEqual(int(result.get("is_maintenance_due") or 0), 1)
		self.assertEqual(int(result.get("has_die_tool") or 0), 1)

	def test_get_die_tool_counter_returns_zero_payload_when_item_has_no_die_tool(self) -> None:
		from production_entry_app.production_entry_app.api import get_die_tool_counter

		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000, has_die_tool=0)
		result = get_die_tool_counter(self.fg_item)
		self.assertEqual(int(result.get("has_die_tool") or 0), 0)
		self.assertEqual(float(result.get("current_strokes") or 0), 0.0)
		self.assertEqual(float(result.get("utilization_pct") or 0), 0.0)
		self.assertEqual(int(result.get("is_maintenance_due") or 0), 0)
		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_get_die_tool_counter_returns_zero_payload_for_non_item_code(self) -> None:
		from production_entry_app.production_entry_app.api import get_die_tool_counter

		non_item_code = "BOM-_SHIFT_AGG_FG-001"
		result = get_die_tool_counter(non_item_code)
		self.assertEqual(result.get("die_tool_code"), non_item_code)
		self.assertEqual(int(result.get("has_die_tool") or 0), 0)
		self.assertEqual(float(result.get("current_strokes") or 0), 0.0)
		self.assertEqual(float(result.get("utilization_pct") or 0), 0.0)
		self.assertEqual(int(result.get("is_maintenance_due") or 0), 0)
		self.assertFalse(frappe.db.exists("Die Tool Counter", non_item_code))

	def test_get_die_tool_counter_returns_safe_payload_when_counter_snapshot_missing(self) -> None:
		from production_entry_app.production_entry_app.api import get_die_tool_counter

		with patch(
			"production_entry_app.production_entry_app.api.get_counter_snapshot",
			return_value=None,
		):
			result = get_die_tool_counter(self.fg_item)

		self.assertEqual(result.get("die_tool_code"), self.fg_item)
		self.assertEqual(int(result.get("has_die_tool") or 0), 1)
		self.assertEqual(float(result.get("current_strokes") or 0), 0.0)
		self.assertEqual(float(result.get("stroke_capacity") or 0), 0.0)
		self.assertEqual(float(result.get("utilization_pct") or 0), 0.0)
		self.assertEqual(int(result.get("is_maintenance_due") or 0), 0)

	def test_reset_die_tool_counter_api_returns_zero(self) -> None:
		from production_entry_app.production_entry_app.api import reset_die_tool_counter

		if frappe.db.exists("Die Tool Counter", self.fg_item):
			frappe.db.set_value(
				"Die Tool Counter",
				self.fg_item,
				{
					"current_stroke_count": 200,
					"stroke_capacity": 1000,
				},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Die Tool Counter",
					"die_tool_item": self.fg_item,
					"current_stroke_count": 200,
					"stroke_capacity": 1000,
				}
			).insert(ignore_permissions=True)

		result = reset_die_tool_counter(self.fg_item, "2026-05-03 10:00:00")
		self.assertEqual(float(result.get("current_strokes") or 0), 0.0)
		self.assertTrue(result.get("maintenance_log"))
		maintenance = frappe.get_doc("Die Tool Maintenance Log", result.get("maintenance_log"))
		self.assertEqual(maintenance.docstatus, 1)
		self.assertEqual(maintenance.die_tool_item, self.fg_item)

	def test_reset_die_tool_counter_api_rejects_disabled_item(self) -> None:
		from production_entry_app.production_entry_app.api import reset_die_tool_counter

		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000, has_die_tool=0)
		with self.assertRaises(ValidationError):
			reset_die_tool_counter(self.fg_item, "2026-05-03 10:00:00")

	def test_update_counter_ignores_non_manufacture_purpose(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		doc = frappe._dict(
			{
				"purpose": "Material Transfer",
				"fg_item": self.fg_item,
				"fg_completed_qty": 10,
			}
		)
		update_counter_for_stock_entry(doc, direction=1)

		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_update_counter_ignores_when_fg_item_missing(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_completed_qty": 10,
				"items": [{"item_code": self.rm_item, "qty": 10}],
			}
		)
		update_counter_for_stock_entry(doc, direction=1)

		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_update_counter_ignores_when_die_tool_disabled(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		_set_item_die_tool_fields(self.fg_item, strokes_per_unit=12, stroke_capacity=1000, has_die_tool=0)
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": self.fg_item,
				"fg_completed_qty": 10,
			}
		)
		update_counter_for_stock_entry(doc, direction=1)

		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_update_counter_ignores_when_strokes_per_unit_not_set(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		frappe.db.set_value("Item", self.fg_item, "custom_pea_strokes_per_unit", 0)
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": self.fg_item,
				"fg_completed_qty": 10,
			}
		)
		update_counter_for_stock_entry(doc, direction=1)

		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_update_counter_ignores_when_total_units_zero(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": self.fg_item,
				"fg_completed_qty": 0,
				"custom_pea_rejection_qty": 0,
				"items": [],
			}
		)
		update_counter_for_stock_entry(doc, direction=1)

		self.assertFalse(frappe.db.exists("Die Tool Counter", self.fg_item))

	def test_update_counter_decrement_clamps_to_zero(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			update_counter_for_stock_entry,
		)

		frappe.get_doc(
			{
				"doctype": "Die Tool Counter",
				"die_tool_item": self.fg_item,
				"current_stroke_count": 5,
				"stroke_capacity": 1000,
			}
		).insert(ignore_permissions=True)
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"fg_item": self.fg_item,
				"fg_completed_qty": 1,
			}
		)

		update_counter_for_stock_entry(doc, direction=-1)

		self.assertEqual(
			float(frappe.db.get_value("Die Tool Counter", self.fg_item, "current_stroke_count") or 0),
			0.0,
		)

	def test_reset_counter_from_maintenance_log_requires_item(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			reset_counter_from_maintenance_log,
		)

		with self.assertRaises(ValidationError):
			reset_counter_from_maintenance_log("", "2026-05-03 10:00:00")

	def test_get_fg_item_code_and_total_units_helpers(self) -> None:
		from production_entry_app.production_entry_app.utils.die_tool_counter import (
			_get_fg_item_code,
			_get_fg_row,
			_get_total_units,
		)

		doc_with_fg_field = frappe._dict({"fg_item": self.fg_item})
		self.assertEqual(_get_fg_item_code(doc_with_fg_field), self.fg_item)

		doc_with_fg_row = frappe._dict(
			{
				"items": [
					{"item_code": self.rm_item, "qty": 2},
					{"item_code": self.fg_item, "qty": 5, "is_finished_item": 1},
				],
				"custom_pea_rejection_qty": 2,
			}
		)
		self.assertEqual(_get_fg_item_code(doc_with_fg_row), self.fg_item)
		self.assertEqual(_get_total_units(doc_with_fg_row), 7.0)
		self.assertIsNotNone(_get_fg_row(doc_with_fg_row))

		doc_without_fg = frappe._dict({"items": [{"item_code": self.rm_item, "qty": 2}]})
		self.assertIsNone(_get_fg_item_code(doc_without_fg))
		self.assertEqual(_get_total_units(doc_without_fg), 0.0)
		self.assertIsNone(_get_fg_row(doc_without_fg))


class TestStockEntryLateEntryStamp(FrappeTestCase):
	def setUp(self) -> None:
		self.masters = bootstrap_manufacture_masters()

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_entry_against_completed_shift_is_flagged_late(self) -> None:
		shift = make_completed_shift(self.masters)
		se = make_direct_manufacture_entry(self.masters, shift=shift.name, fg_qty=100, rejection_qty=0)
		se.submit()
		self.assertEqual(se.custom_pea_is_late_entry, 1)

	def test_entry_against_running_shift_is_not_flagged_late(self) -> None:
		shift = make_running_shift(self.masters)
		se = make_direct_manufacture_entry(self.masters, shift=shift.name, fg_qty=100, rejection_qty=0)
		se.submit()
		self.assertFalse(se.custom_pea_is_late_entry)
