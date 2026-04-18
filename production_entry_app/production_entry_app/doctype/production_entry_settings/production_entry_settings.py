from __future__ import annotations

from frappe.model.document import Document

from production_entry_app.production_entry_app import access_control


class ProductionEntrySettings(Document):
	pass


def on_update(doc: Document, method: str | None = None) -> None:
	del doc, method
	access_control.invalidate_access_control_cache()
