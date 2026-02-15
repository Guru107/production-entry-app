from frappe.model.document import Document

from production_entry_app.production_entry_app.utils.die_tool_counter import (
	reset_counter_from_maintenance_log,
)


class DieToolMaintenanceLog(Document):
	def on_submit(self) -> None:
		reset_counter_from_maintenance_log(self.die_tool_item, self.maintenance_date)
