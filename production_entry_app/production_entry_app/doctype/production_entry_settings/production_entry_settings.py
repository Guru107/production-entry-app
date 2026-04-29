from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control


class ProductionEntrySettings(Document):
	def validate(self) -> None:
		if not self.enable_access_control:
			return
		if not str(self.write_role or "").strip():
			frappe.throw(_("Write Role is mandatory when access control is enabled."))
		if not str(self.read_role or "").strip():
			frappe.throw(_("Read Role is mandatory when access control is enabled."))


def on_update(doc: Document, method: str | None = None) -> None:
	del doc, method
	access_control.invalidate_access_control_cache()
