from __future__ import annotations

import datetime
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.shift.shift import _resolve_shift_company
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	bootstrap_manufacturing_test_context,
	cleanup_running_shifts,
	ensure_branch,
	ensure_default_bom,
	ensure_department,
	ensure_item,
	ensure_warehouse,
	ensure_workstation,
	get_company_abbr,
	resolve_test_branch,
	resolve_test_company,
)

_USE_DURATION = object()


def _ensure_downtime_reasons() -> None:
	"""Ensure planned-loss Downtime Reasons exist and are active."""
	if not frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
		frappe.reload_doc("production_entry_app", "doctype", "downtime_reason")
		frappe.clear_cache(doctype="Downtime Reason")
	for name in ("Shift Start Up", "JH Activity", "Tea Break", "Lunch Break", "Dinner"):
		if not frappe.db.exists("Downtime Reason", name):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()
		if frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
			frappe.db.set_value("Downtime Reason", name, "is_active", 1, update_modified=False)


def _ensure_test_department() -> str:
	return ensure_department("Test Department")


def _cleanup_old_format_shifts_for_dates(*dates: str) -> None:
	"""Delete old-format shifts (SHIFT-{date}.Shift-{label}) for given dates."""
	for shift_date in dates:
		for label in ("1", "2"):
			name = f"SHIFT-{shift_date}.Shift-{label}"
			if frappe.db.exists("Shift", name):
				frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)


def _cleanup_test_department_shift_variants_for_dates(department: str, *dates: str) -> None:
	for shift_date in dates:
		for name in frappe.get_all(
			"Shift",
			filters={"department": department, "shift_date": shift_date},
			pluck="name",
		):
			if frappe.db.exists("Shift", name):
				frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)


def _ensure_loss_entry_shift_field() -> None:
	if frappe.get_meta("Loss Entry", cached=True).has_field("shift"):
		return
	frappe.reload_doc("production_entry_app", "doctype", "loss_entry")
	frappe.clear_cache(doctype="Loss Entry")


def _ensure_shift_duration_options() -> None:
	shift_meta = frappe.get_meta("Shift", cached=True)
	shift_duration = shift_meta.get_field("shift_duration")
	options = (shift_duration.options or "").splitlines() if shift_duration else []
	if "14" in options and "16" in options and shift_meta.get_field("company"):
		return
	frappe.reload_doc("production_entry_app", "doctype", "shift")
	frappe.clear_cache(doctype="Shift")


class TestShift(FrappeTestCase):
	def setUp(self) -> None:
		bootstrap_manufacturing_test_context("SHIFT-CORE")
		_ensure_shift_duration_options()
		_ensure_downtime_reasons()
		_ensure_loss_entry_shift_field()
		self._test_department = _ensure_test_department()
		self._test_branch = ensure_branch(resolve_test_branch() or "_Test Branch")
		frappe.defaults.set_user_default("branch", self._test_branch)
		frappe.defaults.set_user_default("Branch", self._test_branch)
		# End any stale Running shifts so start_shift() is not blocked
		for sn in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
			frappe.db.set_value("Shift", sn, "status", "Completed", update_modified=False)
		# Clean up any shifts on today's date to prevent overlap with
		# test_defaults_are_populated_on_insert which uses frappe.utils.today()
		for sn in frappe.get_all("Shift", filters={"shift_date": frappe.utils.today()}, pluck="name"):
			frappe.delete_doc("Shift", sn, force=True, ignore_permissions=True)
		# Delete old-format shifts (SHIFT-{date}.Shift-{label}) for common test dates
		_cleanup_old_format_shifts_for_dates(
			"2026-02-06",
			"2026-02-07",
			"2026-02-09",
			"2026-02-10",
			"2026-02-11",
			"2026-02-12",
			"2026-02-13",
			"2026-02-14",
			"2026-02-15",
			"2026-02-16",
			"2026-02-17",
			"2026-02-18",
			"2026-02-19",
			"2026-02-20",
			"2026-02-21",
			"2026-02-22",
			"2026-02-23",
			"2026-02-24",
			"2026-02-25",
			"2026-02-26",
			"2026-02-27",
			"2026-02-28",
			"2026-03-01",
			"2026-03-02",
			"2026-03-03",
			"2026-03-10",
			"2026-03-11",
			"2026-03-12",
			"2026-03-17",
			"2026-04-01",
			"2026-04-14",
			"2026-04-15",
			"2026-05-15",
			"2026-05-16",
			"2026-05-17",
			"2026-05-18",
			"2026-05-19",
			"2026-05-20",
			"2026-06-01",
			"2026-09-01",
			"2026-09-02",
			"2026-09-03",
			"2026-09-10",
			"2026-10-01",
			"2026-10-02",
			"2090-01-23",
			"2090-01-24",
		)
		_cleanup_test_department_shift_variants_for_dates(
			self._test_department,
			"2026-02-06",
			"2026-02-07",
			"2026-02-09",
			"2026-02-10",
			"2026-02-11",
			"2026-02-12",
			"2026-02-13",
			"2026-02-14",
			"2026-02-15",
			"2026-02-16",
			"2026-02-17",
			"2026-02-18",
			"2026-02-19",
			"2026-02-20",
			"2026-02-21",
			"2026-02-22",
			"2026-02-23",
			"2026-02-24",
			"2026-02-25",
			"2026-02-26",
			"2026-02-27",
			"2026-02-28",
			"2026-03-01",
			"2026-03-02",
			"2026-03-03",
			"2026-03-10",
			"2026-03-11",
			"2026-03-12",
			"2026-03-17",
			"2026-04-01",
			"2026-04-14",
			"2026-04-15",
			"2026-05-15",
			"2026-05-16",
			"2026-05-17",
			"2026-05-18",
			"2026-05-19",
			"2026-05-20",
			"2026-06-01",
			"2026-09-01",
			"2026-09-02",
			"2026-09-03",
			"2026-09-10",
			"2026-10-01",
			"2026-10-02",
			"2090-01-23",
			"2090-01-24",
		)

	def tearDown(self) -> None:
		frappe.db.rollback()

	def _delete_shifts_for_date(self, shift_date: str) -> None:
		for sn in frappe.get_all("Shift", filters={"shift_date": shift_date}, pluck="name"):
			frappe.delete_doc("Shift", sn, force=True, ignore_permissions=True)

	def _ensure_workstation_and_employee(self) -> tuple[str, str]:
		workstation = frappe.get_all("Workstation", limit=1, pluck="name")
		if workstation:
			workstation_name = workstation[0]
		else:
			workstation_name = "Shift Test Workstation"
			frappe.get_doc(
				{
					"doctype": "Workstation",
					"workstation_name": workstation_name,
					"production_capacity": 1,
					"hour_rate": 100,
				}
			).insert(ignore_permissions=True)

		employee = frappe.get_all("Employee", limit=1, pluck="name")
		if employee:
			employee_name = employee[0]
		else:
			company = resolve_test_company()
			abbr = get_company_abbr(company)
			employee_name = (
				frappe.get_doc(
					{
						"doctype": "Employee",
						"first_name": "Shift",
						"last_name": "Tester",
						"gender": "Female",
						"date_of_birth": "1990-01-01",
						"date_of_joining": "2020-01-01",
						"company": company,
						"status": "Active",
						"employee_number": f"SHIFT-EMP-{abbr}",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		return workstation_name, employee_name

	def test_defaults_are_populated_on_insert(self) -> None:
		self._delete_shift_if_exists(self._expected_name(self._test_department, frappe.utils.today(), "1"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
			}
		).insert()

		self.assertEqual(doc.shift_date, frappe.utils.today())
		self.assertTrue(doc.planned_start_time)
		self.assertTrue(doc.planned_end_time)
		self.assertEqual(doc.supervisor, frappe.session.user)
		self.assertEqual(doc.company, frappe.db.get_single_value("Global Defaults", "default_company"))

	def test_department_sanitized_in_name(self) -> None:
		"""Shift autoname uses the next date sequence."""
		name = self._expected_name(self._test_department, "2026-05-20", "1")
		self._delete_shift_if_exists(name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-05-20",
			}
		).insert()
		self.assertEqual(doc.name, name)
		self.assertEqual(doc.name, "SHIFT-2026-05-20.1.0001")
		self.assertTrue(doc.name.endswith(".0001"))

	def test_department_display_name_used_in_name(self) -> None:
		department = ensure_department("Display Name Department")
		frappe.db.set_value(
			"Department",
			department,
			"department_name",
			"Press Shop",
			update_modified=False,
		)
		_cleanup_old_format_shifts_for_dates("2026-05-21")
		_cleanup_test_department_shift_variants_for_dates(department, "2026-05-21")
		name = self._expected_name(department, "2026-05-21", "1")
		self._delete_shift_if_exists(name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-05-21",
			}
		).insert()
		self.assertEqual(doc.name, "SHIFT-2026-05-21.1.0001")

	def test_shift_company_field_is_present_on_meta(self) -> None:
		meta = frappe.get_meta("Shift")
		company_field = meta.get_field("company")
		self.assertIsNotNone(company_field)
		self.assertEqual(company_field.fieldtype, "Link")
		self.assertEqual(company_field.options, "Company")

	def test_resolve_shift_company_prefers_current_value(self) -> None:
		self.assertEqual(
			_resolve_shift_company(
				current_company="Company A",
				default_company="Company B",
				default_exists=True,
				company_count=2,
				sole_company=None,
			),
			"Company A",
		)

	def test_resolve_shift_company_uses_default_or_sole_company(self) -> None:
		self.assertEqual(
			_resolve_shift_company(
				current_company=None,
				default_company="Company B",
				default_exists=True,
				company_count=2,
				sole_company=None,
			),
			"Company B",
		)
		self.assertEqual(
			_resolve_shift_company(
				current_company=None,
				default_company=None,
				default_exists=False,
				company_count=1,
				sole_company="Company A",
			),
			"Company A",
		)

	def test_planned_end_time_is_calculated(self) -> None:
		self._delete_shift_if_exists(self._expected_name(self._test_department, "2026-02-06", "2"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-06",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.planned_end_time, "16:00:00")
		self.assertEqual(doc.shift_end_date, "2026-02-06")

	def test_midnight_crossing_sets_shift_end_date(self) -> None:
		self._delete_shift_if_exists(self._expected_name(self._test_department, "2026-02-07", "1"))
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "10",
				"shift_date": "2026-02-07",
				"planned_start_time": "22:00:00",
			}
		).insert()

		self.assertEqual(doc.planned_end_time, "08:00:00")
		self.assertEqual(doc.shift_end_date, "2026-02-08")

	def test_name_format(self) -> None:
		# Use date unlikely to collide with test_defaults (which uses frappe.utils.today())
		expected_name = self._expected_name(self._test_department, "2026-04-01", "2")
		self._delete_shift_if_exists(expected_name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-04-01",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.name, expected_name)

	def test_status_state_colors_use_standard_mapping(self) -> None:
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		frappe.clear_cache(doctype="Shift")
		meta = frappe.get_meta("Shift")
		state_map = {row.title: row.color for row in meta.states}
		self.assertEqual(state_map.get("Draft"), "Orange")
		self.assertEqual(state_map.get("Running"), "Blue")
		self.assertEqual(state_map.get("Completed"), "Green")
		self.assertEqual(state_map.get("Cancelled"), "Red")

	def test_status_transitions_via_actions(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-09", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-09",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.status, "Draft")

		doc.start_shift()
		doc.reload()
		self.assertEqual(doc.status, "Running")

		doc.end_shift()
		doc.reload()
		self.assertEqual(doc.status, "Completed")

	def test_status_transition_draft_to_cancelled(self) -> None:
		name = self._expected_name(self._test_department, "2026-05-15", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-05-15",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(doc.status, "Draft")

		doc.cancel_shift()
		doc.reload()
		self.assertEqual(doc.status, "Cancelled")

	def test_start_shift_adds_status_audit_comment(self) -> None:
		name = self._expected_name(self._test_department, "2026-05-16", "1")
		self._delete_shift_if_exists(name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-05-16",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc.start_shift()
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Shift", "reference_name": name},
			pluck="content",
		)
		self.assertTrue(any("Status changed to" in (c or "") and "Running" in (c or "") for c in comments))

	def test_end_shift_adds_status_audit_comment(self) -> None:
		name = self._expected_name(self._test_department, "2026-05-17", "1")
		self._delete_shift_if_exists(name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-05-17",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()
		doc.end_shift()

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Shift", "reference_name": name},
			pluck="content",
		)
		self.assertTrue(any("Status changed to" in (c or "") and "Completed" in (c or "") for c in comments))

	def test_cancel_shift_adds_status_audit_comment(self) -> None:
		name = self._expected_name(self._test_department, "2026-05-18", "2")
		self._delete_shift_if_exists(name)
		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-05-18",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.cancel_shift()

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Shift", "reference_name": name},
			pluck="content",
		)
		self.assertTrue(any("Status changed to" in (c or "") and "Cancelled" in (c or "") for c in comments))

	def test_cancel_shift_not_allowed_from_running(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-16", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-16",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()

		with self.assertRaises(ValidationError):
			doc.cancel_shift()

	def test_planned_losses_locked_in_running_state(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-17", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-17",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertEqual(len(doc.planned_losses), 3)

		doc.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		# Modifying planned_losses should be rejected
		doc.planned_losses = []
		with self.assertRaises(ValidationError):
			doc.save()

		# End shift so it does not leak into subsequent tests (e.g. conflict check)
		frappe.get_doc("Shift", name).end_shift()

	def test_warehouse_defaults_can_be_edited_in_running_state(self) -> None:
		shift_date = "2026-03-17"
		name = self._expected_name(self._test_department, shift_date, "1")
		self._delete_shift_if_exists(name)
		company = resolve_test_company()
		abbr = get_company_abbr(company)
		initial_wip = ensure_warehouse(f"Shift Running WIP A - {abbr}", company)
		updated_wip = ensure_warehouse(f"Shift Running WIP B - {abbr}", company)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00",
				"work_in_progress_warehouse": initial_wip,
			}
		).insert()
		doc.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value

		running_doc = frappe.get_doc("Shift", name)
		running_doc.work_in_progress_warehouse = updated_wip
		running_doc.save()

		reloaded = frappe.get_doc("Shift", name)
		self.assertEqual(reloaded.work_in_progress_warehouse, updated_wip)

		# End shift so it does not leak into subsequent tests (e.g. conflict check)
		reloaded.end_shift()

	def test_document_locked_in_completed_state(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-18", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-18",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()
		doc.end_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		doc.shift_duration = "10"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_document_locked_in_cancelled_state(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-19", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-19",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.cancel_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_field_locking sees persisted status via get_value
		doc = frappe.get_doc("Shift", name)

		doc.supervisor = "Administrator"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_field_locking_uses_doc_before_save_before_db_lookup(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import Shift

		doc = frappe.new_doc("Shift")
		doc.name = "SHIFT-TEST-LOCKING"
		doc.flags.allow_status_change = False
		doc.planned_losses = []
		doc.get_doc_before_save = lambda: frappe._dict({"status": "Running", "planned_losses": []})
		doc._planned_losses_changed = lambda: False

		with patch(
			"production_entry_app.production_entry_app.doctype.shift.shift.frappe.db.get_value"
		) as get_value:
			Shift._validate_field_locking(doc)
		get_value.assert_not_called()

	def test_planned_losses_auto_populate_8_hour_shift(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-11", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-11",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 3)

		startup, jh_activity, tea = doc.planned_losses[0], doc.planned_losses[1], doc.planned_losses[2]
		self.assertEqual(startup.downtime_reason, "Shift Start Up")
		self.assertEqual(startup.start_time, "08:00:00")
		self.assertEqual(startup.end_time, "08:10:00")

		self.assertEqual(jh_activity.downtime_reason, "JH Activity")
		self.assertEqual(jh_activity.start_time, "08:10:00")
		self.assertEqual(jh_activity.end_time, "08:20:00")

		self.assertEqual(tea.downtime_reason, "Tea Break")
		self.assertEqual(tea.start_time, "09:00:00")
		self.assertEqual(tea.end_time, "09:10:00")

	def test_planned_losses_auto_populate_10_hour_shift(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-12", "2")
		self._delete_shift_if_exists(name)
		# Clean up any stale Shift-1 on same date to prevent overlap
		self._delete_shift_if_exists(self._expected_name(self._test_department, "2026-02-12", "1"))

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "10",
				"shift_date": "2026-02-12",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 5)

		rows = [(row.downtime_reason, row.start_time, row.end_time) for row in doc.planned_losses]
		self.assertEqual(
			rows,
			[
				("Shift Start Up", "08:00:00", "08:10:00"),
				("JH Activity", "08:10:00", "08:20:00"),
				("Tea Break", "09:00:00", "09:10:00"),
				("Lunch Break", "12:00:00", "12:30:00"),
				("Tea Break", "17:00:00", "17:10:00"),
			],
		)

	def test_planned_losses_auto_populate_12_hour_shift(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-13", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "12",
				"shift_date": "2026-02-13",
				"planned_start_time": "06:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 5)

		rows = [(row.downtime_reason, row.start_time, row.end_time) for row in doc.planned_losses]
		self.assertEqual(
			rows,
			[
				("Shift Start Up", "06:00:00", "06:10:00"),
				("JH Activity", "06:10:00", "06:20:00"),
				("Tea Break", "09:00:00", "09:10:00"),
				("Lunch Break", "12:00:00", "12:30:00"),
				("Tea Break", "17:00:00", "17:20:00"),
			],
		)

	def test_planned_losses_auto_populate_14_hour_shift(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-15", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "14",
				"shift_date": "2026-02-15",
				"planned_start_time": "08:00:00",
			}
		).insert()

		rows = [(row.downtime_reason, row.start_time, row.end_time) for row in doc.planned_losses]
		self.assertEqual(
			rows,
			[
				("Shift Start Up", "08:00:00", "08:10:00"),
				("JH Activity", "08:10:00", "08:20:00"),
				("Tea Break", "09:00:00", "09:10:00"),
				("Lunch Break", "12:00:00", "12:30:00"),
				("Tea Break", "17:00:00", "17:20:00"),
				("Tea Break", "20:00:00", "20:10:00"),
			],
		)

	def test_planned_losses_auto_populate_16_hour_shift(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-16", "2")
		self._delete_shift_if_exists(name)
		self._delete_shift_if_exists(self._expected_name(self._test_department, "2026-02-16", "1"))

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "16",
				"shift_date": "2026-02-16",
				"planned_start_time": "08:00:00",
			}
		).insert()

		rows = [(row.downtime_reason, row.start_time, row.end_time) for row in doc.planned_losses]
		self.assertEqual(
			rows,
			[
				("Shift Start Up", "08:00:00", "08:10:00"),
				("JH Activity", "08:10:00", "08:20:00"),
				("Tea Break", "09:00:00", "09:10:00"),
				("Lunch Break", "12:00:00", "12:30:00"),
				("Tea Break", "17:00:00", "17:20:00"),
				("Tea Break", "20:00:00", "20:10:00"),
				("Dinner", "22:00:00", "22:30:00"),
			],
		)

	def test_planned_losses_repopulate_when_shift_duration_changes(self) -> None:
		self._delete_shifts_for_date("2026-02-14")
		name = self._expected_name(self._test_department, "2026-02-14", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-14",
				"planned_start_time": "08:00:00",
			}
		).insert()

		self.assertEqual(len(doc.planned_losses), 3)

		doc.shift_duration = "10"
		doc.save()

		self.assertEqual(len(doc.planned_losses), 5)
		self.assertEqual(doc.planned_losses[4].downtime_reason, "Tea Break")
		self.assertEqual(doc.planned_losses[4].start_time, "17:00:00")

	def test_inactive_downtime_reason_not_included_in_planned_losses(self) -> None:
		if not frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
			self.skipTest("Downtime Reason.is_active field is not available in current schema.")
		name = self._expected_name(self._test_department, "2026-06-01", "1")
		self._delete_shift_if_exists(name)
		original_tea_state = frappe.db.get_value("Downtime Reason", "Tea Break", "is_active")
		try:
			frappe.db.set_value("Downtime Reason", "Tea Break", "is_active", 0, update_modified=False)
			doc = frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"shift_label": "1",
					"shift_duration": "10",
					"shift_date": "2026-06-01",
					"planned_start_time": "08:00:00",
				}
			).insert()
			reasons = [row.downtime_reason for row in doc.planned_losses]
			self.assertNotIn("Tea Break", reasons)
			self.assertIn("Lunch Break", reasons)
		finally:
			frappe.db.set_value(
				"Downtime Reason",
				"Tea Break",
				"is_active",
				1 if original_tea_state is None else original_tea_state,
				update_modified=False,
			)

	def test_break_schedule_keys_match_valid_durations(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			_FIXED_TIME_BREAKS,
			VALID_SHIFT_DURATIONS,
		)

		self.assertEqual(set(_FIXED_TIME_BREAKS.keys()), set(VALID_SHIFT_DURATIONS))

	def test_invalid_shift_duration_message_lists_valid_options(self) -> None:
		name = self._expected_name(self._test_department, "2026-05-19", "1")
		self._delete_shift_if_exists(name)
		with self.assertRaises(ValidationError) as exc:
			frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"shift_label": "1",
					"shift_duration": "9",
					"shift_date": "2026-05-19",
					"planned_start_time": "08:00:00",
				}
			).insert()
		self.assertIn("8, 10, 12, 14, 16", str(exc.exception))

	def test_status_cannot_be_changed_directly(self) -> None:
		name = self._expected_name(self._test_department, "2026-02-10", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-10",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc.status = "Running"
		with self.assertRaises(ValidationError):
			doc.save()

	def test_overlap_validation_prevents_overlapping_shifts(self) -> None:
		"""Two shifts on same date with overlapping times must be rejected."""
		name1 = self._expected_name(self._test_department, "2026-02-20", "1")
		name2 = self._expected_name(self._test_department, "2026-02-20", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-20",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_no_overlapping_shifts sees first shift when inserting second

		# Shift 2: 10:00-18:00 overlaps Shift 1: 08:00-16:00
		with self.assertRaises(ValidationError) as cm:
			frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"branch": self._test_branch,
					"shift_label": "2",
					"shift_duration": "8",
					"shift_date": "2026-02-20",
					"planned_start_time": "10:00:00",
				}
			).insert()
		self.assertIn("overlap", str(cm.exception).lower())

	def test_non_overlapping_shifts_allowed(self) -> None:
		"""Shifts that do not overlap on the same date are allowed."""
		self._delete_shifts_for_date("2026-02-21")

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-21",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertEqual(doc1.name, "SHIFT-2026-02-21.1.0001")

		# Shift 2: 16:00-24:00 (midnight) - ends 00:00 next day, does not overlap 08:00-16:00
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-21",
				"planned_start_time": "16:00:00",
			}
		).insert()
		self.assertEqual(doc2.name, "SHIFT-2026-02-21.2.0002")

	def test_overlap_query_scopes_to_nearby_dates(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import Shift

		doc = frappe.new_doc("Shift")
		doc.department = self._test_department
		doc.branch = self._test_branch
		doc.shift_date = "2026-02-21"
		doc.planned_start_time = "08:00:00"
		doc.shift_end_date = "2026-02-21"
		doc.planned_end_time = "16:00:00"
		doc.name = "SHIFT-2026-02-21.Shift-1"

		with patch(
			"production_entry_app.production_entry_app.doctype.shift.shift.frappe.qb.from_"
		) as qb_from:
			query = qb_from.return_value.select.return_value
			query.where.return_value = query
			query.limit.return_value = query
			query.run.return_value = []
			Shift._validate_no_overlapping_shifts(doc)

		qb_from.assert_called_once()
		query.run.assert_called_once_with(as_dict=True)

	def test_overlap_still_detected_for_cross_midnight_neighbor_day(self) -> None:
		self._delete_shifts_for_date("2026-04-14")
		self._delete_shifts_for_date("2026-04-15")
		name1 = self._expected_name(self._test_department, "2026-04-14", "1")
		name2 = self._expected_name(self._test_department, "2026-04-15", "1")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-04-14",
				"planned_start_time": "22:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - ensure first shift is visible to overlap check

		with self.assertRaises(ValidationError):
			frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"branch": self._test_branch,
					"shift_label": "1",
					"shift_duration": "8",
					"shift_date": "2026-04-15",
					"planned_start_time": "05:00:00",
				}
			).insert()

	def test_unique_shift_label_per_date_validation(self) -> None:
		"""Only one Shift label per date within the same department and branch."""
		name = self._expected_name(self._test_department, "2026-02-22", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-22",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so _validate_unique_shift_label_per_date sees first shift when inserting second

		# Second Shift 1 on same date must fail
		with self.assertRaises(ValidationError) as cm:
			frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"branch": self._test_branch,
					"shift_label": "1",
					"shift_duration": "8",
					"shift_date": "2026-02-22",
					"planned_start_time": "18:00:00",
				}
			).insert()
		self.assertIn("shift", str(cm.exception).lower())
		self.assertIn("1", str(cm.exception))

	def test_same_shift_label_different_dates_allowed(self) -> None:
		"""Shift 1 on different dates is allowed."""
		name1 = self._expected_name(self._test_department, "2026-02-23", "1")
		name2 = self._expected_name(self._test_department, "2026-02-24", "1")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-23",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-24",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertEqual(doc1.name, name1)
		self.assertEqual(doc2.name, name2)

	def test_get_linked_downtime_entries_returns_overlapping_downtimes(self) -> None:
		"""get_linked_downtime_entries returns Downtime Entries whose time overlaps with the Shift."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_linked_downtime_entries,
		)

		workstation, employee = self._ensure_workstation_and_employee()

		name = self._expected_name(self._test_department, "2026-03-10", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-10",
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so get_linked_downtime_entries sees shift

		# Downtime 10:00-11:00 overlaps with shift 08:00-16:00
		dt_overlap = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": workstation,
				"operator": employee,
				"from_time": "2026-03-10 10:00:00",
				"to_time": "2026-03-10 11:00:00",
				"stop_reason": "Other",
			}
		).insert()
		# Downtime 18:00-19:00 does NOT overlap with shift 08:00-16:00
		dt_no_overlap = frappe.get_doc(
			{
				"doctype": "Downtime Entry",
				"workstation": workstation,
				"operator": employee,
				"from_time": "2026-03-10 18:00:00",
				"to_time": "2026-03-10 19:00:00",
				"stop_reason": "Other",
			}
		).insert()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

		result = get_linked_downtime_entries(name)
		names = [r["name"] for r in result]
		self.assertIn(dt_overlap.name, names)
		self.assertNotIn(dt_no_overlap.name, names)

		# Cleanup
		frappe.delete_doc("Downtime Entry", dt_overlap.name, force=True)
		frappe.delete_doc("Downtime Entry", dt_no_overlap.name, force=True)
		frappe.delete_doc("Shift", name, force=True)

	def test_update_shift_can_change_own_times_without_false_overlap(self) -> None:
		"""Updating a shift (e.g. duration) should not falsely overlap with itself."""
		name = self._expected_name(self._test_department, "2026-02-25", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-25",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.shift_duration = "10"
		doc.save()
		doc.reload()
		self.assertEqual(doc.shift_duration, "10")

	def test_notification_created_on_shift_start(self) -> None:
		"""Notification Log is created when shift transitions to Running."""
		name = self._expected_name(self._test_department, "2026-02-26", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-26",
				"planned_start_time": "08:00:00",
			}
		).insert()
		before_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		doc.start_shift()
		after_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		self.assertGreater(after_count, before_count)

	def test_notification_created_on_shift_end(self) -> None:
		"""Notification Log is created when shift transitions to Completed."""
		name = self._expected_name(self._test_department, "2026-02-27", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-27",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc.start_shift()
		before_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		doc.end_shift()
		after_count = frappe.db.count("Notification Log", {"document_type": "Shift", "document_name": name})
		self.assertGreater(after_count, before_count)

	def test_notification_recipients_query_user_emails_in_batch(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			_get_notification_recipients_for_shift,
		)

		shift = frappe._dict({"supervisor": "supervisor@example.com"})

		with patch(
			"production_entry_app.production_entry_app.doctype.shift.shift.frappe.db.get_value",
			return_value="supervisor@example.com",
		):
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.get_all",
				side_effect=[["manager1@example.com"], ["manager1@factory.local"]],
			) as get_all:
				emails = _get_notification_recipients_for_shift(shift)

		self.assertEqual(emails, ["supervisor@example.com", "manager1@factory.local"])
		self.assertTrue(any(call.args and call.args[0] == "User" for call in get_all.call_args_list))

	def test_notification_recipients_user_query_filters_enabled_users(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			_get_notification_recipients_for_shift,
		)

		shift = frappe._dict({"supervisor": "supervisor@example.com"})

		with patch(
			"production_entry_app.production_entry_app.doctype.shift.shift.frappe.db.get_value",
			return_value="supervisor@example.com",
		):
			with patch(
				"production_entry_app.production_entry_app.doctype.shift.shift.frappe.get_all",
				side_effect=[["manager1@example.com"], ["manager1@factory.local"]],
			) as get_all:
				_get_notification_recipients_for_shift(shift)

		user_calls = [call for call in get_all.call_args_list if call.args and call.args[0] == "User"]
		self.assertEqual(len(user_calls), 1)
		self.assertEqual(user_calls[0].kwargs.get("filters", {}).get("enabled"), 1)

	def test_running_shift_conflict_detected(self) -> None:
		"""check_running_shift_conflict returns conflict when another shift is Running."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		name1 = self._expected_name(self._test_department, "2026-02-28", "1")
		name2 = self._expected_name(self._test_department, "2026-02-28", "2")
		self._delete_shift_if_exists(name1)
		self._delete_shift_if_exists(name2)

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "16:00:00",
			}
		).insert()

		# Start Shift 1
		name1 = doc1.name
		name2 = doc2.name
		doc1 = frappe.get_doc("Shift", name1)
		doc1.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so check sees Running shift

		# Shift 2 (Draft) checking for conflict should find Shift 1 Running
		result = check_running_shift_conflict(name2)
		self.assertTrue(result.get("has_conflict"))
		self.assertIn(name1, [s["name"] for s in result.get("conflicting_shifts", [])])

		# End Shift 1 so it does not leak into subsequent tests
		frappe.get_doc("Shift", name1).end_shift()

	def test_start_shift_blocked_when_another_running(self) -> None:
		"""start_shift raises error when another shift in the same department and branch is already Running."""
		self._delete_shifts_for_date("2026-02-28")

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "16:00:00",
			}
		).insert()

		# Start Shift 1
		name1 = doc1.name
		name2 = doc2.name
		doc1 = frappe.get_doc("Shift", name1)
		doc1.start_shift()

		# Trying to start Shift 2 should be blocked
		doc2 = frappe.get_doc("Shift", name2)
		with self.assertRaises(frappe.ValidationError):
			doc2.start_shift()

		# End Shift 1 so it does not leak
		frappe.get_doc("Shift", name1).end_shift()

	def test_start_shift_allows_other_branch_running_shift(self) -> None:
		other_branch = ensure_branch("Concurrent Test Branch")
		self._delete_shifts_for_date("2026-02-28")

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": other_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-02-28",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc1.start_shift()
		doc2 = frappe.get_doc("Shift", doc2.name)
		doc2.start_shift()

		self.assertEqual(frappe.db.get_value("Shift", doc2.name, "status"), "Running")

		frappe.get_doc("Shift", doc1.name).end_shift()
		frappe.get_doc("Shift", doc2.name).end_shift()

	def test_no_running_shift_conflict_when_none_running(self) -> None:
		"""check_running_shift_conflict returns no conflict when no other shift is Running."""
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		# End any Running shifts from previous tests to ensure clean state
		for shift_name in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
			frappe.db.set_value("Shift", shift_name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so check_running_shift_conflict sees no Running shifts

		name = self._expected_name(self._test_department, "2026-03-01", "1")
		self._delete_shift_if_exists(name)

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-01",
				"planned_start_time": "08:00:00",
			}
		).insert()

		result = check_running_shift_conflict(name)
		self.assertFalse(result.get("has_conflict"))
		self.assertEqual(result.get("conflicting_shifts"), [])

	def test_running_shift_conflict_ignores_other_branch(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			check_running_shift_conflict,
		)

		other_branch = ensure_branch("Conflict-Free Branch")
		self._delete_shifts_for_date("2026-03-02")

		doc1 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-02",
				"planned_start_time": "08:00:00",
			}
		).insert()
		doc2 = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": other_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-03-02",
				"planned_start_time": "16:00:00",
			}
		).insert()

		doc1.start_shift()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so check sees Running shift

		result = check_running_shift_conflict(doc2.name)
		self.assertFalse(result.get("has_conflict"))
		self.assertEqual(result.get("conflicting_shifts"), [])

		frappe.get_doc("Shift", doc1.name).end_shift()

	def test_branch_field_can_be_set(self) -> None:
		if not frappe.db.exists("Branch", "Test Branch"):
			frappe.get_doc({"doctype": "Branch", "branch": "Test Branch"}).insert(ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-11",
				"planned_start_time": "08:00:00",
				"branch": "Test Branch",
			}
		).insert()
		self.assertEqual(doc.branch, "Test Branch")

	def test_branch_is_required_when_no_default_is_available(self) -> None:
		for key in ("branch", "Branch"):
			frappe.defaults.clear_user_default(key)
		for name in frappe.get_all("Branch", pluck="name"):
			frappe.delete_doc("Branch", name, force=True, ignore_permissions=True)

		with self.assertRaises(ValidationError):
			frappe.get_doc(
				{
					"doctype": "Shift",
					"department": self._test_department,
					"shift_label": "1",
					"shift_duration": "8",
					"shift_date": "2026-03-12",
					"planned_start_time": "08:00:00",
				}
			).insert()

		self._test_branch = ensure_branch("_Test Branch")
		frappe.defaults.set_user_default("branch", self._test_branch)
		frappe.defaults.set_user_default("Branch", self._test_branch)

	def test_same_department_different_branch_overlap_is_allowed(self) -> None:
		other_branch = ensure_branch("Other Test Branch")
		self._delete_shifts_for_date("2026-03-13")

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-13",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": other_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-13",
				"planned_start_time": "10:00:00",
			}
		).insert()
		self.assertEqual(doc.name, "SHIFT-2026-03-13.1.0002")

	def test_same_shift_label_different_branch_same_date_allowed(self) -> None:
		other_branch = ensure_branch("Another Test Branch")
		self._delete_shifts_for_date("2026-03-14")

		frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-14",
				"planned_start_time": "08:00:00",
			}
		).insert()

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": other_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-14",
				"planned_start_time": "16:00:00",
			}
		).insert()
		self.assertEqual(doc.name, "SHIFT-2026-03-14.1.0002")

	def _expected_name(self, department: str, shift_date: str, shift_label: str) -> str:
		sequence = frappe.db.count("Shift", {"shift_date": shift_date}) + 1
		return f"SHIFT-{shift_date}.{shift_label}.{sequence:04d}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)


class TestShiftLayout(FrappeTestCase):
	def setUp(self) -> None:
		frappe.reload_doc("production_entry_app", "doctype", "shift")
		frappe.clear_cache(doctype="Shift")

	def _field_index(self, meta, fieldname: str) -> int:
		for index, field in enumerate(meta.fields):
			if field.fieldname == fieldname:
				return index
		self.fail(f"Field not found in Shift meta: {fieldname}")

	def test_tabs_exist(self) -> None:
		meta = frappe.get_meta("Shift")
		for fieldname in (
			"tab_overview",
			"tab_warehouses",
			"tab_breaks",
			"tab_activity",
			"tab_metrics",
			"tab_aggregate_entries",
		):
			field = meta.get_field(fieldname)
			self.assertTrue(field, f"Expected field {fieldname} to exist")
			self.assertEqual(field.fieldtype, "Tab Break")

	def test_shift_date_is_required(self) -> None:
		meta = frappe.get_meta("Shift")
		field = meta.get_field("shift_date")
		self.assertTrue(field)
		self.assertEqual(int(field.reqd or 0), 1)

	def test_planned_start_helper_field_is_present_and_canonical_is_hidden(self) -> None:
		meta = frappe.get_meta("Shift")
		helper = meta.get_field("planned_start_time_input")
		canonical = meta.get_field("planned_start_time")
		self.assertTrue(helper)
		self.assertEqual(helper.fieldtype, "Data")
		self.assertEqual(int(helper.no_copy or 0), 1)
		self.assertEqual(int(helper.print_hide or 0), 1)
		self.assertEqual(int(helper.search_index or 0), 0)
		self.assertTrue(canonical)
		self.assertEqual(int(canonical.hidden or 0), 1)

	def test_planned_start_helper_field_follows_shift_date(self) -> None:
		meta = frappe.get_meta("Shift")
		self.assertEqual(
			self._field_index(meta, "planned_start_time_input"),
			self._field_index(meta, "shift_date") + 1,
		)

	def test_shift_end_date_is_in_times_column(self) -> None:
		meta = frappe.get_meta("Shift")
		self.assertGreater(
			self._field_index(meta, "shift_end_date"),
			self._field_index(meta, "col_break_times"),
		)

	def test_search_indexes_enabled_for_key_shift_fields(self) -> None:
		meta = frappe.get_meta("Shift")
		for fieldname in ("shift_date", "status", "supervisor"):
			field = meta.get_field(fieldname)
			self.assertTrue(field)
			self.assertEqual(int(field.search_index or 0), 1)

	def test_warehouse_fields_follow_warehouses_tab(self) -> None:
		meta = frappe.get_meta("Shift")
		tab_start = self._field_index(meta, "tab_warehouses")
		next_tab = self._field_index(meta, "tab_breaks")
		for fieldname in (
			"raw_material_warehouse",
			"work_in_progress_warehouse",
			"rejection_warehouse",
			"scrap_warehouse",
		):
			idx = self._field_index(meta, fieldname)
			self.assertGreater(idx, tab_start)
			self.assertLess(idx, next_tab)

	def test_planned_losses_follows_breaks_tab(self) -> None:
		meta = frappe.get_meta("Shift")
		idx = self._field_index(meta, "planned_losses")
		self.assertGreater(idx, self._field_index(meta, "tab_breaks"))
		self.assertLess(idx, self._field_index(meta, "tab_activity"))

	def test_linked_downtime_follows_activity_tab(self) -> None:
		meta = frappe.get_meta("Shift")
		linked_idx = self._field_index(meta, "linked_downtime_entries")
		self.assertGreater(linked_idx, self._field_index(meta, "tab_activity"))
		self.assertLess(linked_idx, self._field_index(meta, "tab_metrics"))

	def test_aggregate_entries_follows_metrics_tab(self) -> None:
		meta = frappe.get_meta("Shift")
		aggregate_idx = self._field_index(meta, "aggregate_production_entries")
		self.assertGreater(aggregate_idx, self._field_index(meta, "tab_metrics"))
		self.assertGreater(aggregate_idx, self._field_index(meta, "shift_metrics"))

	def test_loss_entry_helper_fields_are_present_and_canonical_time_fields_are_hidden(self) -> None:
		meta = frappe.get_meta("Loss Entry")
		for fieldname in ("start_time_input", "duration_mins_input", "end_time_input"):
			field = meta.get_field(fieldname)
			self.assertTrue(field, f"Expected Loss Entry field {fieldname} to exist")
			self.assertEqual(int(field.no_copy or 0), 1)
			self.assertEqual(int(field.print_hide or 0), 1)
			self.assertEqual(int(field.search_index or 0), 0)

		for fieldname in ("start_time", "end_time"):
			field = meta.get_field(fieldname)
			self.assertTrue(field)
			self.assertEqual(int(field.hidden or 0), 1)

	def test_loss_entry_helper_fields_are_ordered_before_hidden_time_fields(self) -> None:
		meta = frappe.get_meta("Loss Entry")
		self.assertLess(
			self._field_index(meta, "start_time_input"),
			self._field_index(meta, "start_time"),
		)
		self.assertLess(
			self._field_index(meta, "duration_mins_input"),
			self._field_index(meta, "end_time"),
		)
		self.assertLess(
			self._field_index(meta, "end_time_input"),
			self._field_index(meta, "end_time"),
		)


class TestShiftSummary(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.ctx = bootstrap_manufacturing_test_context("SHIFT-SUMMARY")

	def setUp(self) -> None:
		_ensure_downtime_reasons()
		cleanup_running_shifts()
		_cleanup_old_format_shifts_for_dates(
			"2026-09-01",
			"2026-09-02",
			"2026-09-03",
			"2026-09-04",
			"2026-09-05",
			"2026-09-06",
			"2026-09-07",
			"2026-09-08",
			"2026-09-09",
			"2026-09-10",
		)
		_cleanup_test_department_shift_variants_for_dates(
			_ensure_test_department(),
			"2026-09-01",
			"2026-09-02",
			"2026-09-03",
			"2026-09-04",
			"2026-09-05",
			"2026-09-06",
			"2026-09-07",
			"2026-09-08",
			"2026-09-09",
			"2026-09-10",
		)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _create_shift(self, shift_date: str, shift_label: str = "1"):
		dept = _ensure_test_department()
		branch = ensure_branch(resolve_test_branch() or "_Test Branch")
		for old_name in frappe.get_all("Shift", filters={"shift_date": shift_date}, pluck="name"):
			if frappe.db.exists("Shift", old_name):
				frappe.delete_doc("Shift", old_name, force=True, ignore_permissions=True)
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": dept,
				"branch": branch,
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00",
			}
		).insert()
		frappe.cache().delete_value(f"pea:shift_summary:{shift.name}")
		return shift

	def _create_submitted_like_entry(
		self,
		shift_name: str,
		*,
		total_qty: float,
		rejection_qty: float,
		duration_mins: float = 0,
		production_time_mins: float | None | object = _USE_DURATION,
		standard_spm: float = 0,
		workstation: str | None = None,
		fg_item: str | None = None,
		bom_no: str | None = None,
		unplanned_losses: list[dict] | None = None,
		docstatus: int = 1,
	) -> str:
		production_minutes = duration_mins if production_time_mins is _USE_DURATION else production_time_mins
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Manufacture",
				"purpose": "Manufacture",
				"company": self.ctx["company"],
				"posting_date": "2026-09-01",
				"posting_time": "09:00:00",
				"custom_shift": shift_name,
				"fg_completed_qty": total_qty,
				"custom_rejection_qty": rejection_qty,
				"custom_actual_duration_mins": duration_mins,
				"custom_production_time_mins": production_minutes,
				"custom_standard_spm": standard_spm,
				"custom_workstation": workstation,
				"bom_no": bom_no,
				"docstatus": docstatus,
			}
		)
		entry.db_insert()
		if fg_item:
			frappe.get_doc(
				{
					"doctype": "Stock Entry Detail",
					"parenttype": "Stock Entry",
					"parent": entry.name,
					"parentfield": "items",
					"idx": 1,
					"item_code": fg_item,
					"qty": total_qty,
					"transfer_qty": total_qty,
					"is_finished_item": 1,
					"t_warehouse": self.ctx["fg_warehouse"],
					"basic_rate": 0,
				}
			).db_insert()
		for index, row in enumerate(unplanned_losses or [], start=1):
			frappe.get_doc(
				{
					"doctype": "Loss Entry",
					"parenttype": "Stock Entry",
					"parent": entry.name,
					"parentfield": "custom_unplanned_losses",
					"idx": index,
					"downtime_reason": row.get("downtime_reason"),
					"start_time": row.get("start_time"),
					"end_time": row.get("end_time"),
					"shift": row.get("shift") or shift_name,
				}
			).db_insert()
		return entry.name

	def _ensure_employee(self) -> str:
		employee = frappe.db.get_value("Employee", {"employee_number": "SHIFT-SUMMARY-EMP"}, "name")
		if employee:
			return employee
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Shift",
					"last_name": "Summary",
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"company": self.ctx["company"],
					"status": "Active",
					"employee_number": "SHIFT-SUMMARY-EMP",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _create_downtime_entry(
		self,
		*,
		workstation: str,
		from_time: str,
		to_time: str,
		shift_name: str,
		stop_reason: str = "Other",
	) -> str:
		ensure_workstation(workstation, standard_spm=2)
		return (
			frappe.get_doc(
				{
					"doctype": "Downtime Entry",
					"workstation": workstation,
					"operator": self._ensure_employee(),
					"from_time": from_time,
					"to_time": to_time,
					"shift": shift_name,
					"stop_reason": stop_reason,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_returns_zeroed_summary_when_no_entries(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-01")
		summary = get_shift_summary(shift.name)
		self.assertEqual(summary["snapshot"]["entry_count"], 0)
		self.assertEqual(float(summary["snapshot"]["total_qty"]), 0.0)
		self.assertEqual(float(summary["snapshot"]["ok_qty"]), 0.0)
		self.assertEqual(float(summary["snapshot"]["rejection_qty"]), 0.0)
		self.assertEqual(float(summary["snapshot"]["recorded_production_mins"]), 0.0)
		self.assertEqual(float(summary["snapshot"]["overall_throughput_spm"]), 0.0)
		self.assertEqual(float(summary["snapshot"]["overall_ok_spm"]), 0.0)
		self.assertIsNone(summary["snapshot"]["overall_shift_efficiency_pct"])
		self.assertEqual(float(summary["logged_downtime"]["total_mins"]), 0.0)
		self.assertFalse(summary["logged_downtime"]["recorded"])
		self.assertTrue(summary["completeness"]["show_banner"])

	def test_computes_shift_level_snapshot_metrics_from_totals(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-02")
		self._create_submitted_like_entry(
			shift.name,
			total_qty=60,
			rejection_qty=10,
			duration_mins=30,
			production_time_mins=20,
			standard_spm=2,
			workstation="WS-A",
		)
		self._create_submitted_like_entry(
			shift.name,
			total_qty=40,
			rejection_qty=0,
			duration_mins=20,
			production_time_mins=20,
			standard_spm=2,
			workstation="WS-B",
		)
		summary = get_shift_summary(shift.name)
		self.assertEqual(summary["snapshot"]["entry_count"], 2)
		self.assertAlmostEqual(float(summary["snapshot"]["total_qty"]), 100.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["rejection_qty"]), 10.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["ok_qty"]), 90.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["rejection_pct"]), 10.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["recorded_production_mins"]), 40.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["overall_throughput_spm"]), 2.5, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["overall_ok_spm"]), 2.25, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["target_coverage_pct"]), 100.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["overall_shift_efficiency_pct"]), 125.0, places=6)
		self.assertFalse(summary["completeness"]["show_banner"])

	def test_hides_efficiency_when_target_coverage_below_threshold(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-03")
		self._create_submitted_like_entry(
			shift.name,
			total_qty=100,
			rejection_qty=0,
			duration_mins=30,
			production_time_mins=30,
			standard_spm=2,
		)
		self._create_submitted_like_entry(
			shift.name,
			total_qty=100,
			rejection_qty=0,
			duration_mins=30,
			production_time_mins=30,
			standard_spm=0,
		)
		summary = get_shift_summary(shift.name)
		self.assertAlmostEqual(float(summary["snapshot"]["target_coverage_pct"]), 50.0, places=6)
		self.assertIsNone(summary["snapshot"]["overall_shift_efficiency_pct"])

	def test_explicit_zero_production_minutes_do_not_fallback_to_duration(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-03")
		self._create_submitted_like_entry(
			shift.name,
			total_qty=120,
			rejection_qty=0,
			duration_mins=20,
			production_time_mins=0,
			standard_spm=3,
			workstation="WS-ZERO",
		)
		summary = get_shift_summary(shift.name)
		self.assertAlmostEqual(float(summary["snapshot"]["recorded_production_mins"]), 0.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["overall_throughput_spm"]), 0.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["overall_ok_spm"]), 0.0, places=6)
		self.assertAlmostEqual(float(summary["snapshot"]["target_coverage_pct"]), 0.0, places=6)

	def test_item_bom_exceptions_group_by_item_and_bom(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-03")
		item_a = ensure_item("_SHIFT_SUMMARY_ITEM_A")
		item_b = ensure_item("_SHIFT_SUMMARY_ITEM_B")
		self._create_submitted_like_entry(
			shift.name,
			total_qty=30,
			rejection_qty=10,
			duration_mins=30,
			fg_item=item_a,
			bom_no=None,
		)
		self._create_submitted_like_entry(
			shift.name,
			total_qty=30,
			rejection_qty=1,
			duration_mins=30,
			fg_item=item_b,
			bom_no=None,
		)
		summary = get_shift_summary(shift.name)
		item_boms = summary["exceptions"]["item_boms"]
		self.assertGreaterEqual(len(item_boms), 2)
		self.assertEqual(item_boms[0]["item_code"], item_a)
		self.assertEqual(item_boms[1]["item_code"], item_b)
		self.assertNotEqual(item_boms[0]["label"], item_boms[1]["label"])

	def test_separates_unplanned_losses_from_logged_downtime_incidents(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-04")
		self._create_submitted_like_entry(
			shift.name,
			total_qty=50,
			rejection_qty=5,
			duration_mins=60,
			production_time_mins=30,
			workstation="WS-LINE-1",
			unplanned_losses=[
				{
					"downtime_reason": "Tea Break",
					"start_time": "09:00:00",
					"end_time": "09:10:00",
					"shift": shift.name,
				},
				{
					"downtime_reason": "Lunch Break",
					"start_time": "09:10:00",
					"end_time": "09:30:00",
					"shift": shift.name,
				},
			],
		)
		self._create_downtime_entry(
			workstation="WS-LINE-1",
			from_time="2026-09-04 10:00:00",
			to_time="2026-09-04 10:30:00",
			shift_name=shift.name,
			stop_reason="Other",
		)
		summary = get_shift_summary(shift.name)
		self.assertAlmostEqual(float(summary["losses"]["unplanned_loss_mins"]), 30.0, places=6)
		self.assertEqual(summary["logged_downtime"]["entry_count"], 1)
		self.assertAlmostEqual(float(summary["logged_downtime"]["total_mins"]), 30.0, places=6)
		self.assertTrue(summary["logged_downtime"]["recorded"])
		self.assertEqual(summary["logged_downtime"]["top_reasons"][0]["reason"], "Other")
		self.assertEqual(summary["exceptions"]["unplanned_loss_reasons"][0]["reason"], "Lunch Break")

	def test_logged_downtime_ignores_overlapping_rows_from_other_shifts(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-04")
		other_shift = self._create_shift("2026-09-05")
		self._create_downtime_entry(
			workstation="WS-LINE-1",
			from_time="2026-09-04 10:00:00",
			to_time="2026-09-04 10:15:00",
			shift_name=shift.name,
			stop_reason="Other",
		)
		self._create_downtime_entry(
			workstation="WS-LINE-2",
			from_time="2026-09-04 10:05:00",
			to_time="2026-09-04 10:25:00",
			shift_name=other_shift.name,
			stop_reason="Machine malfunction",
		)

		summary = get_shift_summary(shift.name)
		self.assertEqual(summary["logged_downtime"]["entry_count"], 1)
		self.assertAlmostEqual(float(summary["logged_downtime"]["total_mins"]), 15.0, places=6)
		self.assertEqual(summary["logged_downtime"]["top_reasons"][0]["reason"], "Other")

	def test_running_shift_shows_provisional_completeness_banner(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-05")
		frappe.db.set_value("Shift", shift.name, "status", "Running", update_modified=False)
		summary = get_shift_summary(shift.name)
		self.assertTrue(summary["completeness"]["show_banner"])
		self.assertIn("Running", " ".join(summary["completeness"]["messages"]))

	def test_requires_shift_read_permission(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-10")
		_ensure_user_with_role("test_shift_summary_blogger@example.com", "Blogger")
		user = frappe.get_doc("User", "test_shift_summary_blogger@example.com")
		for role in ("Manufacturing User", "Manufacturing Manager"):
			if role in frappe.get_roles(user.name):
				user.remove_roles(role)
		user.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.set_user(user.name)

		with self.assertRaises(frappe.PermissionError):
			get_shift_summary(shift.name)

	def test_returns_cached_summary_without_querying_database(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-06")
		cached = {
			"snapshot": {"entry_count": 7, "total_qty": 70},
			"losses": {"unplanned_loss_mins": 12},
			"exceptions": {"workstations": []},
			"logged_downtime": {"recorded": False, "entry_count": 0, "total_mins": 0, "top_reasons": []},
			"positive_signal": None,
			"completeness": {"show_banner": False, "messages": []},
		}
		with patch(
			"production_entry_app.production_entry_app.doctype.shift.shift._get_cached_shift_summary",
			return_value=cached,
		):
			summary = get_shift_summary(shift.name)
		self.assertEqual(summary, cached)

	def test_summary_fresh_after_submit_without_waiting_ttl(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_submit_stock_entry,
		)

		shift = self._create_shift("2026-09-07")
		self._create_submitted_like_entry(shift.name, total_qty=50, rejection_qty=0)
		first = get_shift_summary(shift.name)
		self.assertEqual(float(first["snapshot"]["total_qty"]), 50.0)

		new_entry_name = self._create_submitted_like_entry(shift.name, total_qty=30, rejection_qty=0)
		with patch(
			"production_entry_app.production_entry_app.overrides.stock_entry_hooks.update_counter_for_stock_entry"
		):
			on_submit_stock_entry(frappe.get_doc("Stock Entry", new_entry_name), "on_submit")

		second = get_shift_summary(shift.name)
		self.assertEqual(float(second["snapshot"]["total_qty"]), 80.0)

	def test_summary_fresh_after_shift_status_change_without_waiting_ttl(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_summary,
			invalidate_shift_summary_for_shift,
		)

		shift = self._create_shift("2026-09-08")
		self._create_submitted_like_entry(shift.name, total_qty=50, rejection_qty=0)
		first = get_shift_summary(shift.name)
		self.assertFalse(first["completeness"]["show_banner"])

		frappe.db.set_value("Shift", shift.name, "status", "Running", update_modified=False)
		invalidate_shift_summary_for_shift(frappe.get_doc("Shift", shift.name), "on_update")

		second = get_shift_summary(shift.name)
		self.assertTrue(second["completeness"]["show_banner"])
		self.assertIn("Running", " ".join(second["completeness"]["messages"]))

	def test_summary_fresh_after_downtime_insert_without_waiting_ttl(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary

		shift = self._create_shift("2026-09-09")
		first = get_shift_summary(shift.name)
		self.assertEqual(first["logged_downtime"]["entry_count"], 0)

		self._create_downtime_entry(
			workstation="WS-LINE-3",
			from_time="2026-09-09 10:00:00",
			to_time="2026-09-09 10:20:00",
			shift_name=shift.name,
			stop_reason="Other",
		)

		second = get_shift_summary(shift.name)
		self.assertEqual(second["logged_downtime"]["entry_count"], 1)
		self.assertAlmostEqual(float(second["logged_downtime"]["total_mins"]), 20.0, places=4)


class TestShiftAggregateProductionEntries(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.ctx = bootstrap_manufacturing_test_context("SHIFT-AGG")

	def setUp(self) -> None:
		cleanup_running_shifts()
		_cleanup_old_format_shifts_for_dates("2026-10-01", "2026-10-02")
		_cleanup_test_department_shift_variants_for_dates(
			_ensure_test_department(),
			"2026-10-01",
			"2026-10-02",
		)
		self.fg_item = ensure_item("_SHIFT_AGG_FG")
		self.rm_item = ensure_item("_SHIFT_AGG_RM")
		self.bom = ensure_default_bom(self.fg_item, self.rm_item, self.ctx["company"])

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _create_shift(self, shift_date: str, shift_label: str = "1"):
		dept = _ensure_test_department()
		branch = ensure_branch(resolve_test_branch() or "_Test Branch")
		for old_name in frappe.get_all("Shift", filters={"shift_date": shift_date}, pluck="name"):
			if frappe.db.exists("Shift", old_name):
				frappe.delete_doc("Shift", old_name, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Shift",
				"department": dept,
				"branch": branch,
				"shift_label": shift_label,
				"shift_duration": "8",
				"shift_date": shift_date,
				"planned_start_time": "08:00:00",
			}
		).insert()

	def _create_submitted_like_entry(
		self,
		shift_name: str,
		*,
		good_qty: float,
		rejection_qty: float,
		duration_mins: float,
		production_time_mins: float | None | object = _USE_DURATION,
		bom_no: str | None = None,
		purpose: str = "Manufacture",
	) -> str:
		production_minutes = duration_mins if production_time_mins is _USE_DURATION else production_time_mins
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Manufacture",
				"purpose": purpose,
				"company": self.ctx["company"],
				"posting_date": "2026-10-01",
				"posting_time": "09:00:00",
				"custom_shift": shift_name,
				"bom_no": bom_no,
				"fg_completed_qty": good_qty,
				"custom_rejection_qty": rejection_qty,
				"custom_actual_duration_mins": duration_mins,
				"custom_production_time_mins": production_minutes,
				"docstatus": 1,
			}
		)
		entry.db_insert()
		return entry.name

	def test_returns_empty_when_no_entries(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-01")
		rows = get_shift_aggregate_production_entries(shift.name)
		self.assertEqual(rows, [])

	def test_requires_shift_read_permission(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-02")
		_ensure_user_with_role("test_shift_agg_blogger@example.com", "Blogger")
		user = frappe.get_doc("User", "test_shift_agg_blogger@example.com")
		for role in ("Manufacturing User", "Manufacturing Manager"):
			if role in frappe.get_roles(user.name):
				user.remove_roles(role)
		user.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.set_user(user.name)

		with self.assertRaises(frappe.PermissionError):
			get_shift_aggregate_production_entries(shift.name)

	def test_aggregates_bom_based_quantities(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-03")
		self._create_submitted_like_entry(
			shift.name,
			good_qty=100,
			rejection_qty=5,
			duration_mins=60,
			bom_no=self.bom,
		)
		self._create_submitted_like_entry(
			shift.name,
			good_qty=50,
			rejection_qty=3,
			duration_mins=30,
			bom_no=self.bom,
		)
		rows = get_shift_aggregate_production_entries(shift.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["bom_used"], self.bom)
		self.assertEqual(rows[0]["item_code"], self.fg_item)
		self.assertEqual(float(rows[0]["total_qty"]), 150.0)
		self.assertEqual(float(rows[0]["total_reject_qty"]), 8.0)
		self.assertEqual(float(rows[0]["total_ok_qty"]), 142.0)
		expected_avg_spm = 142 / 90
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(rows[0]["avg_spm"]), expected_avg_spm, delta=derived_abs_tol)

	def test_avg_spm_is_zero_when_total_duration_is_zero(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-04")
		self._create_submitted_like_entry(
			shift.name,
			good_qty=40,
			rejection_qty=2,
			duration_mins=0,
			bom_no=self.bom,
		)
		rows = get_shift_aggregate_production_entries(shift.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(float(rows[0]["avg_spm"]), 0.0)

	def test_avg_spm_coalesces_legacy_and_new_rows(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-04")
		self._create_submitted_like_entry(
			shift.name,
			good_qty=100,
			rejection_qty=0,
			duration_mins=60,
			production_time_mins=0,
			bom_no=self.bom,
		)
		self._create_submitted_like_entry(
			shift.name,
			good_qty=50,
			rejection_qty=0,
			duration_mins=30,
			production_time_mins=10,
			bom_no=self.bom,
		)
		rows = get_shift_aggregate_production_entries(shift.name)
		self.assertEqual(len(rows), 1)
		expected_avg_spm = 150 / 70
		derived_abs_tol = 1e-6
		self.assertAlmostEqual(float(rows[0]["avg_spm"]), expected_avg_spm, delta=derived_abs_tol)

	def test_ignores_non_manufacture_and_missing_bom_rows(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import (
			get_shift_aggregate_production_entries,
		)

		shift = self._create_shift("2026-10-05")
		self._create_submitted_like_entry(
			shift.name,
			good_qty=10,
			rejection_qty=1,
			duration_mins=10,
			bom_no="",
		)
		self._create_submitted_like_entry(
			shift.name,
			good_qty=20,
			rejection_qty=2,
			duration_mins=20,
			bom_no=self.bom,
			purpose="Material Transfer",
		)
		rows = get_shift_aggregate_production_entries(shift.name)
		self.assertEqual(rows, [])


def _ensure_user_with_role(email: str, role: str) -> None:
	"""Create or update user to have the given role."""
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.add_roles(role)
	user.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed for permission tests to see user roles


class TestShiftPermissions(FrappeTestCase):
	"""Verify role-based access control for Shift and Downtime Reason."""

	def setUp(self) -> None:
		bootstrap_manufacturing_test_context("SHIFT-PERM")
		self._test_department = _ensure_test_department()
		self._test_branch = ensure_branch(resolve_test_branch() or "_Test Branch")
		frappe.defaults.set_user_default("branch", self._test_branch)
		frappe.defaults.set_user_default("Branch", self._test_branch)
		_ensure_downtime_reasons()
		frappe.reload_doc("production_entry_app", "doctype", "loss_entry")
		frappe.reload_doc("production_entry_app", "doctype", "rejection_breakup")
		frappe.clear_cache(doctype="Loss Entry")
		frappe.clear_cache(doctype="Rejection Breakup")
		# Ensure Manufacturing User and Manufacturing Manager roles exist (ERPNext)
		if not frappe.db.exists("Role", "Manufacturing User"):
			frappe.get_doc({"doctype": "Role", "role_name": "Manufacturing User"}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("Role", "Manufacturing Manager"):
			frappe.get_doc({"doctype": "Role", "role_name": "Manufacturing Manager"}).insert(
				ignore_permissions=True
			)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_manufacturing_user_can_crud_shift(self) -> None:
		_ensure_user_with_role("test_shift_mfg_user@example.com", "Manufacturing User")
		frappe.set_user("test_shift_mfg_user@example.com")

		name = self._expected_name(self._test_department, "2026-03-02", "1")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-03-02",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertTrue(frappe.db.exists("Shift", doc.name))

		loaded = frappe.get_doc("Shift", doc.name)
		self.assertEqual(loaded.shift_label, "1")

		loaded.shift_duration = "10"
		loaded.save()

		frappe.delete_doc("Shift", doc.name)
		self.assertFalse(frappe.db.exists("Shift", doc.name))

	def test_manufacturing_manager_can_crud_shift(self) -> None:
		_ensure_user_with_role("test_shift_mfg_manager@example.com", "Manufacturing Manager")
		frappe.set_user("test_shift_mfg_manager@example.com")

		name = self._expected_name(self._test_department, "2026-03-03", "2")
		self._delete_shift_if_exists(name)

		doc = frappe.get_doc(
			{
				"doctype": "Shift",
				"department": self._test_department,
				"branch": self._test_branch,
				"shift_label": "2",
				"shift_duration": "8",
				"shift_date": "2026-03-03",
				"planned_start_time": "08:00:00",
			}
		).insert()
		self.assertTrue(frappe.db.exists("Shift", doc.name))

		loaded = frappe.get_doc("Shift", doc.name)
		loaded.delete()
		self.assertFalse(frappe.db.exists("Shift", doc.name))

	def test_manufacturing_user_can_crud_downtime_reason(self) -> None:
		_ensure_user_with_role("test_shift_mfg_user@example.com", "Manufacturing User")
		frappe.set_user("test_shift_mfg_user@example.com")

		reason_name = f"Test Downtime Reason {frappe.generate_hash(length=6)}"
		if frappe.db.exists("Downtime Reason", reason_name):
			frappe.delete_doc("Downtime Reason", reason_name)

		doc = frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": reason_name}).insert()
		self.assertTrue(frappe.db.exists("Downtime Reason", doc.name))

		loaded = frappe.get_doc("Downtime Reason", doc.name)
		loaded.delete()
		self.assertFalse(frappe.db.exists("Downtime Reason", doc.name))

	def test_user_without_manufacturing_role_cannot_access_shift(self) -> None:
		"""User with only Blogger role must not have Shift permission."""
		_ensure_user_with_role("test_shift_blogger@example.com", "Blogger")
		user = frappe.get_doc("User", "test_shift_blogger@example.com")
		# Ensure user has only Blogger (remove Manufacturing roles if added elsewhere)
		roles = frappe.get_roles(user.name)
		for role in ("Manufacturing User", "Manufacturing Manager"):
			if role in roles:
				user.remove_roles(role)
				user.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.set_user("test_shift_blogger@example.com")

		self.assertFalse(
			frappe.has_permission("Shift", "read"),
			"User with only Blogger role must not have Shift read permission.",
		)

	def test_loss_entry_permissions_include_manufacturing_roles(self) -> None:
		meta = frappe.get_meta("Loss Entry")
		roles = {perm.role for perm in meta.permissions}
		self.assertIn("Manufacturing User", roles)
		self.assertIn("Manufacturing Manager", roles)

	def test_rejection_breakup_permissions_include_manufacturing_roles(self) -> None:
		meta = frappe.get_meta("Rejection Breakup")
		roles = {perm.role for perm in meta.permissions}
		self.assertIn("Manufacturing User", roles)
		self.assertIn("Manufacturing Manager", roles)

	def _expected_name(self, department: str, shift_date: str, shift_label: str) -> str:
		sequence = frappe.db.count("Shift", {"shift_date": shift_date}) + 1
		return f"SHIFT-{shift_date}.{shift_label}.{sequence:04d}"

	def _delete_shift_if_exists(self, name: str) -> None:
		if frappe.db.exists("Shift", name):
			frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)
