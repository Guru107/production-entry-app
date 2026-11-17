from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import performance_indexes

ALL_SPECS = performance_indexes.OVERLAP_INDEX_SPECS + performance_indexes.REPORT_INDEX_SPECS


class TestPerformanceIndexes(FrappeTestCase):
	def test_ensure_performance_indexes_registers_expected_indexes(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index"
		) as add_index:
			performance_indexes.ensure_performance_indexes()

		actual = [(call.args[0], call.args[1], call.args[2]) for call in add_index.call_args_list]
		self.assertEqual(actual, list(ALL_SPECS))
		self.assertEqual(
			[spec[2] for spec in ALL_SPECS],
			[
				"idx_pea_ste_workstation_actual_window",
				"idx_pea_ste_operator_actual_window",
				"idx_pea_dte_workstation_window",
				"idx_pea_loss_parent_sort",
				"idx_pea_loss_parent_reason",
				"idx_pea_rej_parent_rework",
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

	def test_ensure_performance_indexes_reraises_missing_column_failures(self) -> None:
		missing_column_error = frappe.db.ProgrammingError(
			1054, "Unknown column 'custom_pea_operator' in 'field list'"
		)

		with patch(
			"production_entry_app.production_entry_app.performance_indexes.frappe.db.add_index",
			side_effect=missing_column_error,
		):
			with self.assertRaises(frappe.db.ProgrammingError):
				performance_indexes.ensure_performance_indexes()
