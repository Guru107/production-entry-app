from __future__ import annotations

from typing import Any

import frappe
from frappe.model.document import Document


def is_joint_lh_rh_stock_entry_type(doc: Document) -> bool:
	"""Return whether the selected Stock Entry Type is marked for Joint LH/RH production."""
	return _get_cached_stock_entry_type_flag(
		doc,
		flag_fieldname="custom_pea_joint_lh_rh_production",
		cache_fieldname="pea_joint_stock_entry_type",
	)


def is_rework_stock_entry_type(doc: Document) -> bool:
	"""Return whether the selected Stock Entry Type is marked for Rework."""
	return _get_cached_stock_entry_type_flag(
		doc,
		flag_fieldname="custom_pea_rework_entry",
		cache_fieldname="pea_rework_stock_entry_type",
	)


def _get_cached_stock_entry_type_flag(
	doc: Document,
	*,
	flag_fieldname: str,
	cache_fieldname: str,
) -> bool:
	stock_entry_type = doc.get("stock_entry_type")
	flags = getattr(doc, "flags", None)
	cached = _get_cached_flag(flags, cache_fieldname)
	if cached and cached[0] == stock_entry_type:
		return bool(cached[1])

	is_enabled = bool(
		stock_entry_type
		and frappe.db.get_value("Stock Entry Type", stock_entry_type, flag_fieldname)
	)
	if flags is not None:
		flags[cache_fieldname] = (stock_entry_type, is_enabled)
	return is_enabled


def _get_cached_flag(flags: Any, cache_fieldname: str) -> tuple[str | None, bool] | None:
	if flags is None:
		return None
	cached = flags.get(cache_fieldname) if hasattr(flags, "get") else None
	if isinstance(cached, tuple) and len(cached) == 2:
		return cached
	return None
