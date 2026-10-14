from __future__ import annotations

import frappe
from frappe.locale import get_number_format


def get_system_float_precision() -> int:
	try:
		value = int(frappe.db.get_single_value("System Settings", "float_precision") or 3)
	except (TypeError, ValueError):
		return 3
	return max(value, 0)


def get_system_currency_precision() -> int:
	value = frappe.db.get_single_value("System Settings", "currency_precision")
	if value not in (None, ""):
		try:
			return max(int(value), 0)
		except (TypeError, ValueError):
			return _number_format_precision()
	return _number_format_precision()


def _number_format_precision() -> int:
	try:
		return max(int(get_number_format().precision), 0)
	except (TypeError, ValueError):
		return 2
