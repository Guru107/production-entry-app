from __future__ import annotations

from unittest.mock import patch

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
