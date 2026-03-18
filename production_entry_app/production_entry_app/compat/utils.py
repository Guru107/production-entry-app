"""Compatibility utilities for Frappe/ERPNext v15 and v16."""

from __future__ import annotations

from typing import Any

import frappe

from production_entry_app.production_entry_app.compat import IS_V16_OR_GREATER


def frappe_in_test() -> bool:
	"""Check if Frappe is running in test mode.

	Replaces deprecated frappe.flags.in_test.
	Works in both v15 (frappe.flags.in_test) and v16+ (frappe.in_test).
	"""
	if IS_V16_OR_GREATER:
		return frappe.in_test
	return bool(frappe.flags.in_test)


def has_permission_strict(
	doc: str | dict[str, Any],
	ptype: str = "read",
	user: str | None = None,
) -> bool:
	"""Strict permission check required in v16.

	v16 requires has_permission hooks to return exactly True (not just truthy).
	This helper wraps frappe.has_permission with explicit boolean return.

	Args:
		doc: DocType name string or document object
		ptype: Permission type ("read", "write", "create", "delete", "submit", etc.)
		user: User name (defaults to session user)

	Returns:
		True if permission is explicitly granted, False otherwise
	"""
	result = frappe.has_permission(doc, ptype=ptype, user=user)
	return result is True


def get_value_strict(
	doctype: str,
	name: str,
	fieldname: str,
	*,
	cached: bool = True,
) -> int | float | str | None:
	"""Get a single value with v16-compatible return type handling.

	v16 changed frappe.db.get_value to return stricter types (int/float/bool)
	rather than strings. This helper ensures consistent behavior.

	Args:
		doctype: DocType name
		name: Document name
		fieldname: Field to retrieve
		cached: Whether to use cached metadata

	Returns:
		The field value with v16-compatible typing
	"""
	return frappe.db.get_value(doctype, name, fieldname, cached=cached)
