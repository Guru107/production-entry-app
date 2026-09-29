from __future__ import annotations

import frappe

STANDARD_DOWNTIME_REASONS: dict[str, str] = {
	"00": "Other",
	"01": "Setup",
	"02": "Traceability Change",
	"03": "No Operator",
	"04": "No Material",
	"05": "Maintenance",
	"06": "Tool Repair",
	"07": "No Crane",
	"08": "Await Previous Oprn.",
	"09": "No Stacker",
	"10": "Shift Start Up",
	"11": "No Power",
	"12": "No Air",
	"13": "JH Activity",
	"14": "Tea Break",
	"15": "Quality Problem",
	"16": "Await Prod. Aids",
	"17": "No Schedule",
	"18": "Await Decision",
	"19": "Lunch Break",
	"20": "Dinner",
	"21": "PM",
	"22": "Tool Try-Out",
}


def ensure_downtime_reason(code: str, description: str | None = None) -> None:
	if frappe.db.exists("Downtime Reason", code):
		if frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
			if not frappe.db.get_value("Downtime Reason", code, "is_active"):
				frappe.db.set_value("Downtime Reason", code, "is_active", 1, update_modified=False)
		return
	doc: dict[str, str | int] = {
		"doctype": "Downtime Reason",
		"code": code,
		"description": description or STANDARD_DOWNTIME_REASONS.get(code, code),
	}
	if frappe.get_meta("Downtime Reason", cached=True).has_field("is_active"):
		doc["is_active"] = 1
	frappe.get_doc(doc).insert(ignore_permissions=True)


def seed_standard_downtime_reasons() -> None:
	for code in STANDARD_DOWNTIME_REASONS:
		ensure_downtime_reason(code)
