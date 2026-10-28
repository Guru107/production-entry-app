from __future__ import annotations

import frappe
from frappe.model.utils.rename_field import rename_field


def execute() -> None:
	"""Rename Rejection Breakup.item_code to custom_pea_rb_item_code (#197).

	The unprefixed fieldname let the client's child-table fallback resolve a
	generic ``item_code`` filter (Item dashboard → Stock Entry connection) to
	Rejection Breakup instead of Stock Entry Detail.

	Fresh installs never create the old column; rename_field detects that and
	returns without touching anything.
	"""
	rename_field("Rejection Breakup", "item_code", "custom_pea_rb_item_code")
