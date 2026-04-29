from __future__ import annotations

from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control


class RejectionBreakup(Document):
	def has_permission(self, ptype: str = "read", user: str | None = None) -> bool:
		has_app_permission = access_control.has_gated_doctype_permission(self, ptype=ptype, user=user)
		return has_app_permission and super().has_permission(ptype, user=user)
