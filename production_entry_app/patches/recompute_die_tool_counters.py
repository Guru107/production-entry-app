from __future__ import annotations

import click
import frappe
from frappe.utils import flt

from production_entry_app.production_entry_app.utils.die_tool_counter import recompute_counter


def execute() -> int:
	"""Recompute every Die Tool Counter from submitted entries after its latest active maintenance (#250).

	Earlier cancels and maintenance logs drifted the stored count; the recompute is deterministic,
	so a re-run changes nothing. Returns (and echoes to the migrate output) how many counters changed.
	"""
	precision = frappe.get_precision("Die Tool Counter", "current_stroke_count")
	changed = 0
	for counter in frappe.get_all("Die Tool Counter", fields=["name", "current_stroke_count"]):
		if flt(recompute_counter(counter.name), precision) != flt(counter.current_stroke_count, precision):
			changed += 1
	# Migrate output, not frappe.logger: production logs below ERROR are dropped.
	click.echo(f"recompute_die_tool_counters: {changed} Die Tool Counter(s) changed")
	return changed
