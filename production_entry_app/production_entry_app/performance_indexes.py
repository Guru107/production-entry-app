from __future__ import annotations

import frappe
from frappe.database.utils import drop_index_if_exists

OVERLAP_INDEX_SPECS: tuple[tuple[str, list[str], str], ...] = (
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
)

REPORT_INDEX_SPECS: tuple[tuple[str, list[str], str], ...] = (
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


def ensure_performance_indexes() -> None:
	"""Create targeted composite indexes for high-volume Stock Entry flows."""
	# Current overlap-index order is retained because EXPLAIN on the seeded benchmark
	# dataset selects these indexes for workstation/operator overlap queries. Further
	# redesign is deferred until production-like write-regression measurements show a
	# net gain over this index set.
	for doctype, fields, index_name in OVERLAP_INDEX_SPECS + REPORT_INDEX_SPECS:
		frappe.db.add_index(doctype, fields, index_name)


def ensure_overlap_indexes() -> None:
	for doctype, fields, index_name in OVERLAP_INDEX_SPECS:
		frappe.db.add_index(doctype, fields, index_name)


def drop_overlap_indexes_if_exists() -> None:
	for doctype, _fields, index_name in OVERLAP_INDEX_SPECS:
		drop_index_if_exists(f"tab{doctype}", index_name)
