from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document


class RejectionBreakup(Document):
	pass


def validate_rejection_breakup_row(row: Any) -> float:
	"""Validate fields shared by normal and joint production rejection rows."""
	row_qty = float(row.get("qty") or 0)
	if row_qty <= 0:
		frappe.throw(_("Rejection Breakup rows must have a quantity greater than 0."))
	if not row.get("rejection_reason"):
		frappe.throw(_("Rejection Breakup rows must have a rejection reason."))
	return row_qty
