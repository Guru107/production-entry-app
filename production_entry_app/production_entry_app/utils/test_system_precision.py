from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)


class TestSystemPrecision(FrappeTestCase):
	def test_get_system_float_precision_returns_configured_value(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
			return_value="4",
		):
			self.assertEqual(get_system_float_precision(), 4)

	def test_get_system_float_precision_falls_back_to_three_for_invalid_value(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
			return_value="bad",
		):
			self.assertEqual(get_system_float_precision(), 3)

	def test_get_system_float_precision_falls_back_to_three_for_missing_value(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
			return_value=None,
		):
			self.assertEqual(get_system_float_precision(), 3)

	def test_get_system_float_precision_clamps_negative_values_to_zero(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
			return_value="-2",
		):
			self.assertEqual(get_system_float_precision(), 0)
