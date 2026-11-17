import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class DieToolCounter(Document):
	def validate(self) -> None:
		if not 0 <= flt(self.warning_threshold_pct) <= 100:
			frappe.throw(_("Warning Threshold (%) must be between 0 and 100."))
