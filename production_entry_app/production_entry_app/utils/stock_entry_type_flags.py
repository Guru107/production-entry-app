from __future__ import annotations

import frappe
from frappe.model.document import Document


def is_joint_lh_rh_stock_entry_type(doc: Document | frappe._dict) -> bool:
	"""Return whether the selected Stock Entry Type is marked for Joint LH/RH production."""
	return _get_cached_stock_entry_type_flag(
		doc,
		flag_fieldname="custom_pea_joint_lh_rh_production",
		cache_fieldname="pea_joint_stock_entry_type",
	)


def is_rework_stock_entry_type(doc: Document | frappe._dict) -> bool:
	"""Return whether the selected Stock Entry Type is marked for Rework."""
	return _get_cached_stock_entry_type_flag(
		doc,
		flag_fieldname="custom_pea_rework_entry",
		cache_fieldname="pea_rework_stock_entry_type",
	)


def _get_cached_stock_entry_type_flag(
	doc: Document | frappe._dict,
	*,
	flag_fieldname: str,
	cache_fieldname: str,
) -> bool:
	stock_entry_type = doc.get("stock_entry_type")
	flags = doc.flags or frappe._dict()
	doc.flags = flags
	cached = _get_cached_flag(flags, cache_fieldname)
	if cached and cached[0] == stock_entry_type:
		return bool(cached[1])

	is_enabled = bool(
		stock_entry_type and frappe.db.get_value("Stock Entry Type", stock_entry_type, flag_fieldname)
	)
	flags[cache_fieldname] = (stock_entry_type, is_enabled)
	return is_enabled


def _get_cached_flag(flags: frappe._dict, cache_fieldname: str) -> tuple[str | None, bool] | None:
	return flags.get(cache_fieldname)
