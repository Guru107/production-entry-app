from __future__ import annotations

import datetime

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.loss_time import resolve_time_interval_in_window


class TestLossTime(FrappeTestCase):
	def test_resolve_interval_treats_equal_start_end_as_zero_duration(self) -> None:
		window_start = datetime.datetime(2026, 3, 3, 8, 0, 0)
		window_end = datetime.datetime(2026, 3, 3, 12, 0, 0)

		interval = resolve_time_interval_in_window("10:00:00", "10:00:00", window_start, window_end)

		self.assertIsNone(interval)

	def test_resolve_interval_keeps_cross_midnight_behavior(self) -> None:
		window_start = datetime.datetime(2026, 3, 3, 23, 30, 0)
		window_end = datetime.datetime(2026, 3, 4, 1, 0, 0)

		interval = resolve_time_interval_in_window("23:45:00", "00:15:00", window_start, window_end)

		self.assertIsNotNone(interval)
		start_dt, end_dt = interval
		self.assertEqual(start_dt, datetime.datetime(2026, 3, 3, 23, 45, 0))
		self.assertEqual(end_dt, datetime.datetime(2026, 3, 4, 0, 15, 0))
