from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LossType(Document):
	def validate(self) -> None:
		self._validate_default_duration()

	def _validate_default_duration(self) -> None:
		if self.default_duration is None:
			return

		if self.default_duration <= 0:
			frappe.throw(_("Default Duration must be greater than 0 minutes."))
