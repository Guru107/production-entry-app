from __future__ import annotations

import frappe


def stock_entry_has_branch_field() -> bool:
	return frappe.get_meta("Stock Entry", cached=True).has_field("branch")
