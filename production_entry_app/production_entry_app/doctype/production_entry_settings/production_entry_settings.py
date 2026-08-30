from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from production_entry_app.production_entry_app.utils.production_warehouses import validate_warehouse_companies


class ProductionEntrySettings(Document):
	def validate(self) -> None:
		seen: set[tuple[str, str]] = set()
		for row in self.get("branch_warehouse_defaults") or []:
			key = (row.company, row.branch)
			if key in seen:
				frappe.throw(
					_("Duplicate warehouse defaults for Company {0}, Branch {1}.").format(
						*(frappe.utils.escape_html(value or "") for value in key)
					)
				)
			seen.add(key)
		validate_warehouse_companies(self.get("branch_warehouse_defaults") or [])
