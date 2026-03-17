from __future__ import annotations

import frappe
from frappe import _

from production_entry_app.production_entry_app.doctype.shift.shift import (
	WARNING_THRESHOLD_PCT_DEFAULT,
)
from production_entry_app.production_entry_app.utils.die_tool_counter import get_counter_health


def _get_maintenance_recipients() -> list[str]:
	raw_recipients = getattr(frappe.conf, "die_tool_maintenance_recipients", None)
	if not raw_recipients:
		return []

	if isinstance(raw_recipients, str):
		values = [email.strip() for email in raw_recipients.split(",")]
		return [email for email in values if email]

	if isinstance(raw_recipients, list | tuple | set):
		return [str(email).strip() for email in raw_recipients if str(email).strip()]

	return []


def _get_due_die_tool_counters() -> list[dict]:
	rows = frappe.get_all(
		"Die Tool Counter",
		filters={"stroke_capacity": (">", 0)},
		fields=["name", "die_tool_item", "current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
		order_by="modified desc",
	)
	due: list[dict] = []
	for row in rows:
		current_strokes = float(row.get("current_stroke_count") or 0)
		stroke_capacity = float(row.get("stroke_capacity") or 0)
		threshold = float(row.get("warning_threshold_pct") or WARNING_THRESHOLD_PCT_DEFAULT)
		utilization_pct, is_maintenance_due = get_counter_health(
			current_strokes=current_strokes,
			stroke_capacity=stroke_capacity,
			warning_threshold_pct=threshold,
		)
		if not is_maintenance_due:
			continue
		due.append(
			{
				"name": row.get("name"),
				"die_tool_item": row.get("die_tool_item"),
				"current_stroke_count": current_strokes,
				"stroke_capacity": stroke_capacity,
				"warning_threshold_pct": threshold,
				"utilization_pct": utilization_pct,
			}
		)
	return due


def _build_alert_message(due_counters: list[dict]) -> str:
	lines = [
		_("The following die tool counters have crossed their warning threshold:"),
		"",
	]
	for row in due_counters:
		lines.append(
			_("{0}: {1}% utilized (current: {2}, capacity: {3}, threshold: {4}%)").format(
				row.get("die_tool_item"),
				_format_numeric_fragment(row.get("utilization_pct") or 0),
				_format_numeric_fragment(row.get("current_stroke_count") or 0),
				_format_numeric_fragment(row.get("stroke_capacity") or 0),
				_format_numeric_fragment(row.get("warning_threshold_pct") or WARNING_THRESHOLD_PCT_DEFAULT),
			)
		)
	return "\n".join(lines)


def _format_numeric_fragment(value: float | int) -> str:
	return frappe.format_value(value, df={"fieldtype": "Float"})


def send_daily_die_tool_maintenance_alerts() -> None:
	recipients = _get_maintenance_recipients()
	if not recipients:
		return

	due_counters = _get_due_die_tool_counters()
	if not due_counters:
		return

	subject = _("Die Tool Maintenance Alert: {0} Counter(s) Need Attention").format(len(due_counters))
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=_build_alert_message(due_counters),
		delayed=False,
	)
