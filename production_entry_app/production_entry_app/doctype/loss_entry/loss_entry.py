from __future__ import annotations

from frappe.model.document import Document


class LossEntry(Document):
	"""Generic loss entry child table.

	Intended to be reusable across parent doctypes (e.g. Shift now, Manufacture Entry later).
	"""
