import frappe
from frappe.tests.utils import FrappeTestCase


def _counter(warning_threshold_pct: int):
	return frappe.get_doc(
		{"doctype": "Die Tool Counter", "die_tool_item": "X", "warning_threshold_pct": warning_threshold_pct}
	)


class TestDieToolCounter(FrappeTestCase):
	def test_warning_threshold_outside_0_to_100_is_rejected(self) -> None:
		for value in (-1, 101, 1000):
			with self.assertRaises(frappe.ValidationError):
				_counter(value).validate()

	def test_warning_threshold_within_range_is_accepted(self) -> None:
		for value in (0, 90, 100):
			_counter(value).validate()
