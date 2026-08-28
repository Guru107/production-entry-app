from __future__ import annotations

from typing import Any

import frappe
from frappe.desk import query_report

PEA_REPORT_NAMES: frozenset[str] = frozenset(
	{
		"Daily Strokes SPM Monitor",
		"Die Tool Stroke and Maintenance Report",
		"Item BOM Rejection Hotspots",
		"Item BOM Rework Hotspots",
		"Operator Daily SPM Report",
		"Operator Efficiency Report",
		"Operator Rejection Performance",
		"Operator Rework Performance",
		"Production OEE Report",
		"Rejection Pareto Report",
		"Rejection PPM Report",
		"Rejection Trend Report",
		"Rework Pareto Report",
		"Rework PPM Report",
		"Rework Trend Report",
		"Workstation Efficiency Report",
		"Workstation Rejection Reason Matrix",
		"Workstation Rework Reason Matrix",
	}
)


def _is_pea_read_only(user: str | None = None) -> bool:
	return "PEA Read Only" in frappe.get_roles(user)


def _validate_report_name(report_name: str, user: str | None = None) -> None:
	if _is_pea_read_only(user) and report_name not in PEA_REPORT_NAMES:
		raise frappe.PermissionError


@frappe.whitelist()
def get_script(report_name: str) -> dict:
	_validate_report_name(report_name)
	return query_report.get_script(report_name)


@frappe.whitelist()
@frappe.read_only()
def run(report_name: str, **kwargs: Any) -> dict:
	_validate_report_name(report_name)
	return query_report.run(report_name=report_name, **kwargs)
