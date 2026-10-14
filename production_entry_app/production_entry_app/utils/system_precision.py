from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import flt

try:
	from frappe.locale import get_number_format
except ImportError:  # Frappe v15 keeps number formats in frappe.utils.data
	get_number_format: Any = None


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


def one_unit_tolerance(precision: int) -> float:
	"""One unit at the given precision, matching ERPNext stock quantity tolerance."""
	return 1.0 / (10**precision)


def exceeds_one_unit(left: float, right: float, precision: int) -> bool:
	return abs(flt(left, precision) - flt(right, precision)) > one_unit_tolerance(precision)


@contextmanager
def override_system_precision(fieldname: str, precision: int) -> Iterator[None]:
	previous_value = frappe.db.get_single_value("System Settings", fieldname)
	previous_default = frappe.db.get_default(fieldname)
	frappe.db.set_single_value("System Settings", fieldname, precision)
	frappe.db.set_default(fieldname, precision)
	try:
		yield
	finally:
		frappe.db.set_single_value("System Settings", fieldname, previous_value)
		frappe.db.set_default(
			fieldname,
			previous_default if previous_default is not None else previous_value,
		)


def _number_format_precision() -> int:
	try:
		if get_number_format is not None:
			return max(int(get_number_format().precision), 0)
		from frappe.utils.data import get_number_format_info

		number_format = frappe.db.get_default("number_format") or "#,###.##"
		return max(int(get_number_format_info(number_format)[2]), 0)
	except (TypeError, ValueError):
		return 2
