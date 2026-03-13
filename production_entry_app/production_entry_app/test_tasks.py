from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.tasks import _get_due_die_tool_counters, send_daily_die_tool_maintenance_alerts


class TestTasks(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_alert_sent_when_threshold_exceeded(self) -> None:
		with patch("production_entry_app.tasks._get_maintenance_recipients", return_value=["qa@example.com"]):
			with patch(
				"production_entry_app.tasks._get_due_die_tool_counters",
				return_value=[
					{
						"die_tool_item": "_Task Alert FG",
						"utilization_pct": 95,
						"current_stroke_count": 950,
						"stroke_capacity": 1000,
						"warning_threshold_pct": 90,
					}
				],
			):
				with patch("production_entry_app.tasks.frappe.sendmail") as sendmail:
					send_daily_die_tool_maintenance_alerts()

		sendmail.assert_called_once()
		call_kwargs = sendmail.call_args.kwargs
		self.assertEqual(call_kwargs.get("recipients"), ["qa@example.com"])
		self.assertIn("Need Attention", call_kwargs.get("subject") or "")
		self.assertIn("_Task Alert FG", call_kwargs.get("message") or "")

	def test_no_alert_below_threshold(self) -> None:
		with patch("production_entry_app.tasks._get_maintenance_recipients", return_value=["qa@example.com"]):
			with patch("production_entry_app.tasks._get_due_die_tool_counters", return_value=[]):
				with patch("production_entry_app.tasks.frappe.sendmail") as sendmail:
					send_daily_die_tool_maintenance_alerts()

		sendmail.assert_not_called()

	def test_due_counter_filters_threshold(self) -> None:
		with patch(
			"production_entry_app.tasks.frappe.get_all",
			return_value=[
				{
					"name": "DTC-1",
					"die_tool_item": "_High FG",
					"current_stroke_count": 950,
					"stroke_capacity": 1000,
					"warning_threshold_pct": 90,
				},
				{
					"name": "DTC-2",
					"die_tool_item": "_Low FG",
					"current_stroke_count": 400,
					"stroke_capacity": 1000,
					"warning_threshold_pct": 90,
				},
			],
		):
			due = _get_due_die_tool_counters()

		self.assertEqual(len(due), 1)
		self.assertEqual(due[0].get("die_tool_item"), "_High FG")

	def test_due_counter_uses_exact_threshold_without_runtime_rounding(self) -> None:
		with patch(
			"production_entry_app.tasks.frappe.get_all",
			return_value=[
				{
					"name": "DTC-1",
					"die_tool_item": "_Borderline FG",
					"current_stroke_count": 1000,
					"stroke_capacity": 3000,
					"warning_threshold_pct": 33.3334,
				}
			],
		):
			due = _get_due_die_tool_counters()

		self.assertEqual(due, [])

	def test_alert_message_preserves_unrounded_numeric_fragments(self) -> None:
		with patch("production_entry_app.tasks._get_maintenance_recipients", return_value=["qa@example.com"]):
			with patch(
				"production_entry_app.tasks._get_due_die_tool_counters",
				return_value=[
					{
						"die_tool_item": "_Precision FG",
						"utilization_pct": 95.6789,
						"current_stroke_count": 956.7894,
						"stroke_capacity": 1000.1234,
						"warning_threshold_pct": 95.4321,
					}
				],
			):
				with patch("production_entry_app.tasks.frappe.sendmail") as sendmail:
					send_daily_die_tool_maintenance_alerts()

		message = sendmail.call_args.kwargs.get("message") or ""
		self.assertIn("95.6789", message)
		self.assertIn("956.7894", message)
		self.assertIn("1000.1234", message)
		self.assertIn("95.4321", message)
