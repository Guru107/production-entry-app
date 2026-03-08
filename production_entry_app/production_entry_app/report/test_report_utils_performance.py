from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report import report_utils


class TestReportUtilsPerformance(FrappeTestCase):
	def test_iter_stock_entries_in_chunks_pages_until_empty(self) -> None:
		responses = [
			[{"name": "STE-1"}, {"name": "STE-2"}],
			[{"name": "STE-3"}],
			[],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils.frappe.get_all",
			side_effect=responses,
		) as get_all:
			chunks = list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					chunk_size=2,
				)
			)

		self.assertEqual(chunks, [[{"name": "STE-1"}, {"name": "STE-2"}], [{"name": "STE-3"}]])
		self.assertEqual(get_all.call_count, 2)
		first_call = get_all.call_args_list[0].kwargs
		self.assertEqual(first_call["limit_start"], 0)
		self.assertEqual(first_call["limit_page_length"], 2)
		second_call = get_all.call_args_list[1].kwargs
		self.assertEqual(second_call["limit_start"], 2)
		self.assertEqual(second_call["limit_page_length"], 2)
