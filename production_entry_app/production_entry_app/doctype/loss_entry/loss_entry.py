from __future__ import annotations

from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control


class LossEntry(Document):
	"""Generic loss entry child table.

	Intended to be reusable across parent doctypes (e.g. Shift now, Manufacture Entry later).
	"""

	def has_permission(self, ptype: str = "read", user: str | None = None) -> bool:
		has_app_permission = access_control.has_gated_doctype_permission(self, ptype=ptype, user=user)
		return has_app_permission and self._has_parent_permission(ptype=ptype, user=user)

	def _has_parent_permission(self, *, ptype: str, user: str | None) -> bool:
		parent_doc = getattr(self, "parent_doc", None)
		if parent_doc:
			try:
				return bool(parent_doc.has_permission(ptype=ptype, user=user))
			except TypeError:
				return bool(parent_doc.has_permission(ptype))
		return bool(super().has_permission(ptype, user=user))
