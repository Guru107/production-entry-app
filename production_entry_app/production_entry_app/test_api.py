from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import (
	_assert_e2e_api_allowed,
	_build_e2e_shift_doc,
	_e2e_base_date,
	_get_or_create_e2e_shift,
	_stock_entry_matches_cleanup_target,
	bootstrap_e2e_context,
	cleanup_e2e_context,
	create_e2e_submitted_stock_entry,
)


class TestE2EApi(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_assert_e2e_api_allowed_calls_only_for_administrator(self) -> None:
		with patch("production_entry_app.production_entry_app.api.frappe.only_for") as only_for:
			with patch(
				"production_entry_app.production_entry_app.api._is_developer_mode_enabled",
				return_value=True,
			):
				with patch(
					"production_entry_app.production_entry_app.api._is_allow_e2e_tests_enabled",
					return_value=True,
				):
					_assert_e2e_api_allowed()
		only_for.assert_called_once_with("Administrator")

	def test_assert_e2e_api_allowed_blocks_when_developer_mode_disabled(self) -> None:
		with patch("production_entry_app.production_entry_app.api.frappe.only_for"):
			with patch(
				"production_entry_app.production_entry_app.api._is_developer_mode_enabled",
				return_value=False,
			):
				with self.assertRaises(frappe.PermissionError):
					_assert_e2e_api_allowed()

	def test_assert_e2e_api_allowed_blocks_without_allow_e2e_tests_flag(self) -> None:
		with patch("production_entry_app.production_entry_app.api.frappe.only_for"):
			with patch(
				"production_entry_app.production_entry_app.api._is_developer_mode_enabled",
				return_value=True,
			):
				with patch(
					"production_entry_app.production_entry_app.api._is_allow_e2e_tests_enabled",
					return_value=False,
				):
					with self.assertRaises(frappe.PermissionError):
						_assert_e2e_api_allowed()

	def test_all_e2e_endpoints_fail_closed_when_guard_raises(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.api._assert_e2e_api_allowed",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				bootstrap_e2e_context(prefix="E2E-Guard")
			with self.assertRaises(frappe.PermissionError):
				cleanup_e2e_context(prefix="E2E-Guard")
			with self.assertRaises(frappe.PermissionError):
				create_e2e_submitted_stock_entry(prefix="E2E-Guard")

	def test_stock_entry_matches_cleanup_target_by_operator_or_fg_item(self) -> None:
		operator_only_match = frappe._dict(
			{
				"custom_operator": "E2E Operator",
				"items": [{"is_finished_item": 1, "item_code": "_Another_Item"}],
			}
		)
		self.assertTrue(
			_stock_entry_matches_cleanup_target(
				operator_only_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

		fg_item_only_match = frappe._dict(
			{
				"custom_operator": "Other Operator",
				"items": [{"is_finished_item": 1, "item_code": "_E2E_FG_Item"}],
			}
		)
		self.assertTrue(
			_stock_entry_matches_cleanup_target(
				fg_item_only_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

		no_match = frappe._dict(
			{
				"custom_operator": "Other Operator",
				"items": [{"is_finished_item": 1, "item_code": "_Another_Item"}],
			}
		)
		self.assertFalse(
			_stock_entry_matches_cleanup_target(
				no_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

	def test_e2e_base_date_is_deterministic(self) -> None:
		date_a = _e2e_base_date("StablePrefix")
		date_b = _e2e_base_date("StablePrefix")
		self.assertEqual(date_a, date_b)
		self.assertTrue(date_a.startswith("2099-"))

	def test_cleanup_stock_entry_query_uses_single_qb_run(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.api._get_candidate_e2e_stock_entries",
			return_value=[],
		) as get_candidates:
			with patch("production_entry_app.production_entry_app.api._assert_e2e_api_allowed"):
				with patch(
					"production_entry_app.production_entry_app.api._e2e_base_date",
					return_value="2099-01-10",
				):
					with patch(
						"production_entry_app.production_entry_app.api.frappe.db.exists", return_value=False
					):
						with patch("production_entry_app.production_entry_app.api.frappe.db.commit"):
							cleanup_e2e_context(prefix="E2E")
		get_candidates.assert_called_once_with(
			target_operator="E2E Operator", target_workstation="E2E Workstation"
		)

	def test_cleanup_continues_when_one_stock_entry_delete_fails(self) -> None:
		row1 = frappe._dict({"name": "STE-FAIL", "docstatus": 0})
		row2 = frappe._dict({"name": "STE-OK", "docstatus": 0})
		se1 = frappe._dict(
			{"name": "STE-FAIL", "docstatus": 0, "custom_operator": "E2E Operator", "items": []}
		)
		se2 = frappe._dict({"name": "STE-OK", "docstatus": 0, "custom_operator": "E2E Operator", "items": []})

		with patch(
			"production_entry_app.production_entry_app.api._get_candidate_e2e_stock_entries",
			return_value=[row1, row2],
		):
			with patch("production_entry_app.production_entry_app.api._assert_e2e_api_allowed"):
				with patch(
					"production_entry_app.production_entry_app.api._e2e_base_date",
					return_value="2099-01-10",
				):
					with patch(
						"production_entry_app.production_entry_app.api.frappe.db.exists", return_value=False
					):
						with patch(
							"production_entry_app.production_entry_app.api.frappe.get_doc",
							side_effect=[se1, se2],
						):
							with patch(
								"production_entry_app.production_entry_app.api.frappe.delete_doc",
								side_effect=[Exception("delete failed"), None],
							) as delete_doc:
								with patch(
									"production_entry_app.production_entry_app.api.frappe.log_error"
								) as log_error:
									with patch(
										"production_entry_app.production_entry_app.api.frappe.db.commit"
									):
										cleanup_e2e_context(prefix="E2E")

		self.assertEqual(delete_doc.call_count, 2)
		log_error.assert_called_once()

	def test_build_e2e_shift_doc_contains_expected_fields(self) -> None:
		doc = _build_e2e_shift_doc(
			base_date="2099-01-20",
			wip_warehouse="WIP",
			rm_warehouse="RM",
			rejection_warehouse="REJ",
		)
		self.assertEqual(doc["doctype"], "Shift")
		self.assertEqual(doc["shift_date"], "2099-01-20")
		self.assertEqual(doc["work_in_progress_warehouse"], "WIP")
		self.assertEqual(doc["raw_material_warehouse"], "RM")
		self.assertEqual(doc["rejection_warehouse"], "REJ")

	def test_get_or_create_e2e_shift_keeps_running_shift(self) -> None:
		shift = MagicMock()
		shift.status = "Running"
		with patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True):
			with patch("production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift):
				result = _get_or_create_e2e_shift(
					shift_name="SHIFT-2099-01-20.Shift-1",
					base_date="2099-01-20",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)
		self.assertIs(result, shift)
		shift.start_shift.assert_not_called()

	def test_get_or_create_e2e_shift_starts_draft_shift(self) -> None:
		shift = MagicMock()
		shift.status = "Draft"
		with patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True):
			with patch("production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift):
				result = _get_or_create_e2e_shift(
					shift_name="SHIFT-2099-01-20.Shift-1",
					base_date="2099-01-20",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)
		self.assertIs(result, shift)
		shift.start_shift.assert_called_once()

	def test_get_or_create_e2e_shift_recreates_completed_shift(self) -> None:
		existing = MagicMock()
		existing.status = "Completed"
		recreated = MagicMock()
		recreated.status = "Draft"
		doc_builder = MagicMock()
		doc_builder.insert.return_value = recreated

		with patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True):
			with patch(
				"production_entry_app.production_entry_app.api.frappe.get_doc",
				side_effect=[existing, doc_builder],
			):
				with patch("production_entry_app.production_entry_app.api.frappe.delete_doc") as delete_doc:
					result = _get_or_create_e2e_shift(
						shift_name="SHIFT-2099-01-20.Shift-1",
						base_date="2099-01-20",
						wip_warehouse="WIP",
						rm_warehouse="RM",
						rejection_warehouse="REJ",
					)

		delete_doc.assert_called_once_with(
			"Shift", "SHIFT-2099-01-20.Shift-1", force=True, ignore_permissions=True
		)
		self.assertIs(result, recreated)
		recreated.start_shift.assert_called_once()
