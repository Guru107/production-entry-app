from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc

from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	seed_standard_downtime_reasons,
)

LEGACY_DOWNTIME_REASON_CODES: dict[str, str] = {
	"Other": "00",
	"Mtrl Handl": "00",
	"Tool Break": "00",
	"No Helper": "00",
	"Setup Time": "01",
	"No Operator": "03",
	"No Mtrl": "04",
	"Maint": "05",
	"Shift Start Up": "10",
	"Power Off": "11",
	"JH Activity": "13",
	"Tea Break": "14",
	"Lunch Break": "19",
	"Dinner": "20",
	"P. Maint": "21",
	"Trial": "22",
}


def convert_legacy_downtime_reasons() -> None:
	seed_standard_downtime_reasons()
	for legacy_name, code in LEGACY_DOWNTIME_REASON_CODES.items():
		if frappe.db.exists("Downtime Reason", legacy_name):
			rename_doc(
				"Downtime Reason",
				legacy_name,
				code,
				merge=True,
				force=True,
				show_alert=False,
			)
		else:
			frappe.db.set_value(
				"Loss Entry",
				{"downtime_reason": legacy_name},
				"downtime_reason",
				code,
				update_modified=False,
			)
