from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import performance_indexes


class TestPerformanceIndexes(FrappeTestCase):
	def test_ensure_overlap_indexes_registers_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index"
		) as add_index:
			performance_indexes.ensure_overlap_indexes()

		actual = [(tuple(call.args[0:2]), call.args[2]) for call in add_index.call_args_list]
		expected = [
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_workstation",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_workstation_actual_window",
			),
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_operator",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_operator_actual_window",
			),
			(
				(
					"Downtime Entry",
					["workstation", "from_time", "to_time", "docstatus"],
				),
				"idx_pea_dte_workstation_window",
			),
		]
		self.assertEqual(actual, expected)

	def test_ensure_performance_indexes_registers_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index"
		) as add_index:
			performance_indexes.ensure_performance_indexes()

		actual = [(tuple(call.args[0:2]), call.args[2]) for call in add_index.call_args_list]
		expected = [
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_workstation",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_workstation_actual_window",
			),
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_operator",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_operator_actual_window",
			),
			(
				(
					"Downtime Entry",
					["workstation", "from_time", "to_time", "docstatus"],
				),
				"idx_pea_dte_workstation_window",
			),
			(
				(
					"Loss Entry",
					["parenttype", "parent", "idx"],
				),
				"idx_pea_loss_parent_sort",
			),
			(
				(
					"Loss Entry",
					["parenttype", "parent", "downtime_reason"],
				),
				"idx_pea_loss_parent_reason",
			),
			(
				(
					"Rejection Breakup",
					["parenttype", "parent", "is_rework"],
				),
				"idx_pea_rej_parent_rework",
			),
		]
		self.assertEqual(actual, expected)

	def test_ensure_performance_indexes_with_recovery_registers_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index"
		) as add_index:
			performance_indexes.ensure_performance_indexes_with_recovery()

		actual = [(tuple(call.args[0:2]), call.args[2]) for call in add_index.call_args_list]
		expected = [
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_workstation",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_workstation_actual_window",
			),
			(
				(
					"Stock Entry",
					[
						"purpose",
						"custom_operator",
						"custom_actual_start_date",
						"custom_actual_end_date",
						"docstatus",
					],
				),
				"idx_pea_ste_operator_actual_window",
			),
			(
				(
					"Downtime Entry",
					["workstation", "from_time", "to_time", "docstatus"],
				),
				"idx_pea_dte_workstation_window",
			),
			(
				(
					"Loss Entry",
					["parenttype", "parent", "idx"],
				),
				"idx_pea_loss_parent_sort",
			),
			(
				(
					"Loss Entry",
					["parenttype", "parent", "downtime_reason"],
				),
				"idx_pea_loss_parent_reason",
			),
			(
				(
					"Rejection Breakup",
					["parenttype", "parent", "is_rework"],
				),
				"idx_pea_rej_parent_rework",
			),
		]
		self.assertEqual(actual, expected)

	def test_drop_overlap_indexes_if_exists_drops_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.drop_index_if_exists"
		) as drop_index:
			performance_indexes.drop_overlap_indexes_if_exists()

		self.assertEqual(
			[call.args for call in drop_index.call_args_list],
			[
				("tabStock Entry", "idx_pea_ste_workstation_actual_window"),
				("tabStock Entry", "idx_pea_ste_operator_actual_window"),
				("tabDowntime Entry", "idx_pea_dte_workstation_window"),
			],
		)

	def test_drop_performance_indexes_if_exists_drops_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.drop_index_if_exists"
		) as drop_index:
			performance_indexes.drop_performance_indexes_if_exists()

		self.assertEqual(
			[call.args for call in drop_index.call_args_list],
			[
				("tabStock Entry", "idx_pea_ste_workstation_actual_window"),
				("tabStock Entry", "idx_pea_ste_operator_actual_window"),
				("tabDowntime Entry", "idx_pea_dte_workstation_window"),
				("tabLoss Entry", "idx_pea_loss_parent_sort"),
				("tabLoss Entry", "idx_pea_loss_parent_reason"),
				("tabRejection Breakup", "idx_pea_rej_parent_rework"),
			],
		)

	def test_ensure_performance_indexes_with_recovery_skips_missing_column_failures(self) -> None:
		missing_column_error = frappe.db.ProgrammingError(
			1054, "Unknown column 'custom_operator' in 'field list'"
		)
		total_index_specs = len(performance_indexes.OVERLAP_INDEX_SPECS) + len(
			performance_indexes.REPORT_INDEX_SPECS
		)

		with (
			patch(
				"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index",
				side_effect=[missing_column_error] + ([None] * (total_index_specs - 1)),
			) as add_index,
			patch(
				"production_entry_app.production_entry_app.performance_indexes.frappe.log_error"
			) as log_error,
		):
			performance_indexes.ensure_performance_indexes_with_recovery()

		self.assertEqual(add_index.call_count, total_index_specs)
		log_error.assert_called_once()

	def test_ensure_performance_indexes_reraises_non_missing_column_db_errors(self) -> None:
		other_error = frappe.db.ProgrammingError(1064, "You have an error in your SQL syntax")

		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index",
			side_effect=other_error,
		):
			with self.assertRaises(frappe.db.ProgrammingError):
				performance_indexes.ensure_performance_indexes()

	def test_ensure_performance_indexes_with_recovery_reraises_non_missing_column_db_errors(
		self,
	) -> None:
		other_error = frappe.db.ProgrammingError(1064, "You have an error in your SQL syntax")

		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index",
			side_effect=other_error,
		):
			with self.assertRaises(frappe.db.ProgrammingError):
				performance_indexes.ensure_performance_indexes_with_recovery()

	def test_ensure_overlap_indexes_reraises_missing_column_failures(self) -> None:
		missing_column_error = frappe.db.ProgrammingError(
			1054, "Unknown column 'custom_operator' in 'field list'"
		)

		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index",
			side_effect=missing_column_error,
		):
			with self.assertRaises(frappe.db.ProgrammingError):
				performance_indexes.ensure_overlap_indexes()

	def test_is_missing_column_index_error_matches_known_db_codes(self) -> None:
		self.assertTrue(
			performance_indexes._is_missing_column_index_error(
				frappe.db.ProgrammingError(1054, "Unknown column")
			)
		)
		self.assertTrue(
			performance_indexes._is_missing_column_index_error(
				frappe.db.ProgrammingError(1072, "Key column does not exist")
			)
		)
		self.assertFalse(
			performance_indexes._is_missing_column_index_error(
				frappe.db.ProgrammingError(1064, "Syntax error")
			)
		)
