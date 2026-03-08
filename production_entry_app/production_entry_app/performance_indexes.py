from __future__ import annotations

import frappe


def ensure_performance_indexes() -> None:
	"""Create targeted composite indexes for high-volume Stock Entry flows."""
	# Stock Entry overlap-index redesign is deferred until production-like benchmarks
	# show planner selection and net write-path gain over the current index set.
	index_specs: tuple[tuple[str, list[str], str], ...] = (
		(
			"Stock Entry",
			[
				"purpose",
				"custom_workstation",
				"custom_actual_start_date",
				"custom_actual_end_date",
				"docstatus",
			],
			"idx_pea_ste_workstation_actual_window",
		),
		(
			"Stock Entry",
			[
				"purpose",
				"custom_operator",
				"custom_actual_start_date",
				"custom_actual_end_date",
				"docstatus",
			],
			"idx_pea_ste_operator_actual_window",
		),
		(
			"Downtime Entry",
			["workstation", "from_time", "to_time", "docstatus"],
			"idx_pea_dte_workstation_window",
		),
		(
			"Loss Entry",
			["parenttype", "parent", "idx"],
			"idx_pea_loss_parent_sort",
		),
		(
			"Loss Entry",
			["parenttype", "parent", "downtime_reason"],
			"idx_pea_loss_parent_reason",
		),
		(
			"Rejection Breakup",
			["parenttype", "parent", "is_rework"],
			"idx_pea_rej_parent_rework",
		),
	)

	for doctype, fields, index_name in index_specs:
		frappe.db.add_index(doctype, fields, index_name)
