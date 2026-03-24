from __future__ import annotations

import frappe


def get_system_float_precision() -> int:
	try:
		value = int(frappe.db.get_single_value("System Settings", "float_precision") or 3)
	except (TypeError, ValueError):
		return 3
	return max(value, 0)
