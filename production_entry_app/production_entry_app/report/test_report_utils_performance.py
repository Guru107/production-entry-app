from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.report import report_utils


class TestReportUtilsPerformance(FrappeTestCase):
	def test_iter_stock_entries_in_chunks_pages_by_name_keyset(self) -> None:
		responses = [
			[{"name": "STE-1"}, {"name": "STE-2"}],
			[{"name": "STE-3"}],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		) as fetch_chunk:
			chunks = list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					chunk_size=2,
				)
			)

		self.assertEqual(chunks, [[{"name": "STE-1"}, {"name": "STE-2"}], [{"name": "STE-3"}]])
		self.assertEqual(fetch_chunk.call_count, 2)
		first_call = fetch_chunk.call_args_list[0].kwargs
		self.assertEqual(first_call["order_by"], "name asc")
		self.assertEqual(first_call["chunk_size"], 2)
		self.assertIsNone(first_call["last_row"])
		second_call = fetch_chunk.call_args_list[1].kwargs
		self.assertEqual(second_call["last_row"], {"name": "STE-2"})

	def test_iter_stock_entries_in_chunks_pages_by_posting_date_and_name_keyset(self) -> None:
		responses = [
			[
				{"name": "STE-1", "posting_date": "2026-01-01"},
				{"name": "STE-2", "posting_date": "2026-01-01"},
			],
			[
				{"name": "STE-3", "posting_date": "2026-01-02"},
			],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		) as fetch_chunk:
			chunks = list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name", "posting_date"],
					order_by="posting_date asc, name asc",
					chunk_size=2,
				)
			)

		self.assertEqual(
			chunks,
			[
				[
					{"name": "STE-1", "posting_date": "2026-01-01"},
					{"name": "STE-2", "posting_date": "2026-01-01"},
				],
				[
					{"name": "STE-3", "posting_date": "2026-01-02"},
				],
			],
		)
		second_call = fetch_chunk.call_args_list[1].kwargs
		self.assertEqual(
			second_call["last_row"],
			{"name": "STE-2", "posting_date": "2026-01-01"},
		)

	def test_iter_stock_entries_in_chunks_throws_for_unsupported_order_by(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			list(
				report_utils.iter_stock_entries_in_chunks(
					{"docstatus": 1},
					["name"],
					order_by="creation asc",
				)
			)

	def test_iter_stock_entries_in_chunks_throws_when_max_rows_exceeded(self) -> None:
		responses = [
			[{"name": "STE-1"}, {"name": "STE-2"}],
			[{"name": "STE-3"}],
		]
		with patch(
			"production_entry_app.production_entry_app.report.report_utils._fetch_stock_entry_chunk",
			side_effect=responses,
		):
			with self.assertRaises(frappe.ValidationError):
				list(
					report_utils.iter_stock_entries_in_chunks(
						{"docstatus": 1},
						["name"],
						chunk_size=2,
						max_rows=2,
					)
				)
