from __future__ import annotations

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
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

EXTRA_DOWNTIME_REASON_CODES: dict[str, str] = {
	"Maintenance": "05",
	"Machine Breakdown": "05",
	"Plant Maintenance": "05",
	"No Material": "04",
	"TEA TIME": "14",
	"lunch": "19",
	"Setup 01": "01",
	"5 S ACTIVITY": "13",
	"Material Handling": "00",
	"5 s activity,lunch & tea TIME": "00",
	"tea time & 5s activity": "00",
	"lunch & puwer cut": "00",
	"TEA & TRAINING": "00",
}

CUSTOM_CODE_RANGE: range = range(23, 99)

_KNOWN_LEGACY_REASONS: dict[str, str] = {**LEGACY_DOWNTIME_REASON_CODES, **EXTRA_DOWNTIME_REASON_CODES}


def convert_legacy_downtime_reasons() -> None:
	seed_standard_downtime_reasons()
	for legacy_name, code in _KNOWN_LEGACY_REASONS.items():
		_convert_legacy_master(legacy_name, code)
	assign_codes_to_uncoded_downtime_reasons()


def _convert_legacy_master(legacy_name: str, code: str) -> None:
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


def assign_codes_to_uncoded_downtime_reasons() -> None:
	"""Give every remaining uncoded master a deterministic free code from CUSTOM_CODE_RANGE.

	Pre-migration masters use the reason description as the document name and have
	no two-digit code; mapped legacy names are converted by the maps above. Assigning
	a code renames the document, which rewrites Downtime Reason links on Loss Entry
	rows, and keeps the old name as the description so the label stays readable.
	Uncoded masters are matched with free codes in sorted name order, so a rerun
	from the same starting state lands on the same mapping.
	"""
	rows = frappe.get_all("Downtime Reason", fields=["name", "code"])
	coded_names = {row.name for row in rows if CODE_FORMAT.fullmatch(str(row.name or ""))}
	used_codes = coded_names | {
		str(row.code) for row in rows if row.code and CODE_FORMAT.fullmatch(str(row.code))
	}
	uncoded = sorted(
		row.name for row in rows if row.name not in coded_names and row.name not in _KNOWN_LEGACY_REASONS
	)
	if not uncoded:
		return

	available = [f"{number:02d}" for number in CUSTOM_CODE_RANGE if f"{number:02d}" not in used_codes]
	if len(available) < len(uncoded):
		frappe.throw(
			_(
				"Not enough free Downtime Reason codes: {0} uncoded masters but only {1} codes left in range {2}-{3}."
			).format(len(uncoded), len(available), CUSTOM_CODE_RANGE.start, CUSTOM_CODE_RANGE.stop - 1)
		)

	for old_name, new_code in zip(uncoded, available, strict=False):
		frappe.db.set_value(
			"Downtime Reason",
			old_name,
			{"code": new_code, "description": old_name},
			update_modified=False,
		)
		rename_doc("Downtime Reason", old_name, new_code, force=True, show_alert=False)
