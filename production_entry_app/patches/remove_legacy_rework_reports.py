"""Delete the legacy Rework Register and Daily Rework Report standard reports.

Both were replaced by the Daily Rej Rework Register; Frappe does not remove
standard Report docs whose module files disappear, so they are removed here.
"""

from __future__ import annotations

import frappe

_LEGACY_REPORTS: tuple[str, ...] = ("Rework Register", "Daily Rework Report")


def execute() -> None:
	for report_name in _LEGACY_REPORTS:
		if frappe.db.exists("Report", report_name):
			frappe.delete_doc("Report", report_name, ignore_permissions=True, force=True)
