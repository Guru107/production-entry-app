from __future__ import annotations

from frappe.model.document import Document

class ProductionEntrySettings(Document):
	def validate(self) -> None:
		self.write_role = str(self.write_role or "").strip()
		self.read_role = str(self.read_role or "").strip()

	def on_update(self) -> None:
		pass
