from __future__ import annotations

from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control


class LossEntry(Document):
	"""Generic loss entry child table.

	Intended to be reusable across parent doctypes (e.g. Shift now, Manufacture Entry later).
	"""

	def has_permission(self, ptype: str = "read") -> bool:
		return access_control.has_gated_doctype_permission(self, ptype=ptype)
