import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import get_datetime

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	reset_counter_from_maintenance_log,
)


class DieToolMaintenanceLog(Document):
	def autoname(self) -> None:
		if not self.die_tool_item:
			frappe.throw(_("Die Tool Item is required for naming."))
		maintenance_dt = get_datetime(self.maintenance_date) if self.maintenance_date else None
		date_str = maintenance_dt.strftime("%Y-%m-%d") if maintenance_dt else frappe.utils.nowdate()
		item_code = _sanitize_item_code(self.die_tool_item)
		base = f"DTML-{item_code}-{date_str}"
		raw_name = make_autoname(f"{base}.#####")
		if "." in raw_name:
			self.name = raw_name
			return
		sequence = raw_name[-5:]
		prefix = raw_name[:-5]
		self.name = f"{prefix}.{sequence}"

	def on_submit(self) -> None:
		reset_counter_from_maintenance_log(self.die_tool_item, self.maintenance_date)


def _sanitize_item_code(item_code: str) -> str:
	"""Allow only alphanumerics, dash, and underscore for naming series."""
	allowed = []
	for char in item_code:
		if char.isalnum() or char in {"-", "_"}:
			allowed.append(char)
		else:
			allowed.append("-")
	return "".join(allowed)
