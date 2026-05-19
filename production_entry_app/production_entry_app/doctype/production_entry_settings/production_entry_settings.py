from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control, field_permissions


class ProductionEntrySettings(Document):
	def validate(self) -> None:
		self.write_role = str(self.write_role or "").strip()
		self.read_role = str(self.read_role or "").strip()
		if not self.enable_access_control:
			return
		if not self.write_role:
			frappe.throw(_("Write Role is mandatory when access control is enabled."))
		if not self.read_role:
			frappe.throw(_("Read Role is mandatory when access control is enabled."))

	def on_update(self) -> None:
		write_role = str(self.write_role or "").strip()
		read_role = str(self.read_role or "").strip()
		get_doc_before_save = getattr(self, "get_doc_before_save", None)
		previous = get_doc_before_save() if get_doc_before_save else None
		previous_roles = ()
		if previous:
			previous_roles = (str(previous.write_role or ""), str(previous.read_role or ""))
		access_control.sync_configured_access_roles(
			write_role=write_role,
			read_role=read_role,
			managed_roles=previous_roles,
		)
		field_permissions.ensure_pea_field_permissions(
			write_role=write_role,
			read_role=read_role,
			managed_roles=previous_roles,
		)
