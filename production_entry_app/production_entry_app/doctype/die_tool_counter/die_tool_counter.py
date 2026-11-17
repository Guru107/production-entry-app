import frappe
from frappe import _
from frappe.model.document import Document


class DieToolCounter(Document):
	def validate(self) -> None:
		if not 0 <= (self.warning_threshold_pct or 0) <= 100:
			frappe.throw(_("Warning Threshold (%) must be between 0 and 100."))
